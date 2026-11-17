"""
Metode "EMA M15 + OB/OTE + CHoCH LTF" (dari member grup, metode "dosen trader"), XAUUSD.
Metode terpisah dari pro_strategy (SMC Top-Down) — hanya backtest.

    python -m tg_signal.ote_strategy                 # grid, latih Jun 2025–Mar 2026 vs uji Apr–Nov 2026
    python -m tg_signal.ote_strategy --ltf M5        # konfirmasi/eksekusi di M5 (default M1)

Alur per arah (BUY; SELL kebalikannya, dihitung di ruang harga dinegasikan):
1. Bias M15 (bar M15 terakhir yang sudah close):
   cross    : EMA50 > EMA200
   cross200 : EMA50 > EMA200 dan close > EMA200
2. Zona M15 (dari bar M15 yang sudah close):
   OTE : leg impuls terakhir swing low → swing high (fractal ±2, leg ≥ LEG_MIN);
         zona = retracement 0.618–0.79. Batal bila close M15 di bawah swing low (100%).
   OB  : order block bullish M15 (detectors/poi.py, jenis OB) yang masih utuh, umur ≤ 3 hari.
   zone = ote | ob | either (salah satu) | ob_ote (OB yang beririsan dengan zona OTE aktif).
3. Sesi (opsional): setup baru hanya 07:00–16:00 UTC.
4. Sentuhan: bar LTF menyentuh tepi atas zona dari atas → armed. Batal bila close LTF di bawah
   level invalidasi (OTE: swing low; OB: bawah OB) atau tidak ada konfirmasi dalam ARM_WAIT menit.
5. Konfirmasi CHoCH/MSS LTF: close di atas swing high LTF (fractal ±2) terakhir sebelum low terendah sejak armed.
6. Entry: market = open bar berikutnya | ob = limit di open candle bearish terakhir sebelum kaki
   CHoCH (OB LTF), berlaku PEND_WAIT menit; tidak ada OB → market.
7. SL = low terendah sejak armed − $0.3, risiko $1–$10. TP = RR × risiko, atau liq = swing high
   impuls M15 (target likuiditas; dilewati bila RR < 1.5).
8. Satu posisi per arah, maks 3 trade/hari per arah, stop setelah 2 loss/hari (hari WIB).
Harga bar = BID; BUY masuk di ask, SELL keluar di ask. SL & TP satu bar → SL.
"""
from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal.detectors.poi import find_pois
from tg_signal.market_data import load_m1
from tg_signal.pro_strategy import SPLIT, stats

SESSION_UTC = (7, 16)
LEG_MIN = 3.0                 # $ — leg impuls M15 minimal
OB_MIN = 0.5
OB_AGE_MIN = 3 * 24 * 60      # menit
ARM_WAIT_MIN = 120
PEND_WAIT_MIN = 30
SL_BUF = 0.3
RISK_MIN, RISK_MAX = 1.0, 10.0
LIQ_RR_MIN = 1.5
MAX_TRADES_DAY, MAX_LOSS_DAY = 3, 2
OTE = (0.618, 0.79)


@dataclass(frozen=True)
class Cfg:
    bias: str = "cross"
    zone: str = "either"
    entry: str = "market"
    tp: str = "2"            # "2" | "3" | "liq"
    session: bool = True

    @property
    def name(self) -> str:
        return f"{self.bias}_{self.zone}_{self.entry}_TP{self.tp}_{'ses' if self.session else 'all'}"


def _fractals(h: np.ndarray, l: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = len(h)
    sh, sl = np.zeros(n, bool), np.zeros(n, bool)
    hh = np.lib.stride_tricks.sliding_window_view(h, 5).max(axis=1)
    ll = np.lib.stride_tricks.sliding_window_view(l, 5).min(axis=1)
    sh[2:-2] = h[2:-2] >= hh
    sl[2:-2] = l[2:-2] <= ll
    return sh, sl


def _ote_m15(h, l, c) -> np.ndarray:
    """Per bar M15 k (sudah close): [top, bottom, inval, target, leg_id] zona OTE aktif (NaN bila tidak ada)."""
    n = len(c)
    sh, sl = _fractals(h, l)
    out = np.full((n, 5), np.nan)
    last_sl = None           # (idx, price) swing low terkonfirmasi terakhir
    cur = None               # [top, bottom, inval, target, id]
    for k in range(n):
        j = k - 2            # fractal di j terkonfirmasi saat bar k close
        if j >= 2:
            if sl[j]:
                last_sl = (j, l[j])
            if sh[j] and last_sl is not None and last_sl[0] < j:
                lo = l[last_sl[0]:j + 1].min()
                hi = h[j]
                if hi - lo >= LEG_MIN:
                    rng = hi - lo
                    cur = [hi - OTE[0] * rng, hi - OTE[1] * rng, lo, hi, float(j)]
        if cur is not None and c[k] < cur[2]:
            cur = None
        if cur is not None:
            out[k] = cur
    return out


class Market:
    def __init__(self, m1: pd.DataFrame, ltf: str = "M1"):
        if ltf == "M1":
            df = m1
        else:
            df = m1.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                          "spread": "mean"}).dropna()
        self.bar_min = 1 if ltf == "M1" else 5
        self.df = df
        self.t = df.index.values.astype("datetime64[ns]")
        self.n = len(df)
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.spr = df["spread"].to_numpy(float)
        self.hour = df.index.hour.to_numpy()
        self.day = (df.index + pd.Timedelta(hours=7)).date
        self.arr = {True: (o, h, l, c), False: (-o, -l, -h, -c)}
        self.frac = {b: _fractals(a[1], a[2]) for b, a in self.arr.items()}

        m15 = m1.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        close15 = (m15.index + pd.Timedelta(minutes=15)).values.astype("datetime64[ns]")
        k = np.searchsorted(close15, self.t + np.timedelta64(self.bar_min, "m"), side="right") - 1
        valid = k >= 0
        kk = np.where(valid, k, 0)
        self.k15 = np.where(valid, k, -1)
        e50 = m15["close"].ewm(span=50, adjust=False).mean().to_numpy()
        e200 = m15["close"].ewm(span=200, adjust=False).mean().to_numpy()
        cl = m15["close"].to_numpy()
        warm = np.arange(len(m15)) >= 200
        self.bias = {}
        for is_buy, s in ((True, 1), (False, -1)):
            cross = (s * e50 > s * e200) & warm
            self.bias[("cross", is_buy)] = cross[kk] & valid
            self.bias[("cross200", is_buy)] = (cross & (s * cl > s * e200))[kk] & valid

        to_ltf = np.searchsorted(self.t, close15, side="left") - 1
        self.ote, self.obs = {}, {}
        for is_buy in (True, False):
            a = [m15[x].to_numpy(float) for x in ("open", "high", "low", "close")]
            if not is_buy:
                a = [-a[0], -a[2], -a[1], -a[3]]
            z = _ote_m15(a[1], a[2], a[3])
            self.ote[is_buy] = np.where(valid[:, None], z[kk], np.nan)
            raw = [p for p in find_pois(*a, min_size=OB_MIN) if p.kind == "OB"]
            # (aktif_mulai_ltf, mati_ltf, top, bottom)
            self.obs[is_buy] = [(int(to_ltf[p.created]) + 1,
                                 int(to_ltf[p.dead]) if p.dead < len(m15) else self.n, p.top, p.bottom)
                                for p in raw]


def run_side(mk: Market, cfg: Cfg, is_buy: bool) -> list[dict]:
    O, H, L, C = mk.arr[is_buy]
    spr, n, bm = mk.spr, mk.n, mk.bar_min
    bias = mk.bias[(cfg.bias, is_buy)]
    ote = mk.ote[is_buy]
    obs = mk.obs[is_buy]
    is_sh, _ = mk.frac[is_buy]
    sgn = 1 if is_buy else -1
    arm_wait, pend_wait, ob_age = ARM_WAIT_MIN // bm, PEND_WAIT_MIN // bm, OB_AGE_MIN // bm
    trades: list[dict] = []
    live: list[tuple] = []
    ptr = 0
    used: set = set()
    state = "idle"
    day_key, n_day, loss_day = None, 0, 0
    s: dict = {}

    def close_trade(i, r, why):
        nonlocal state, loss_day
        trades.append({"time": pd.Timestamp(mk.t[s["entry_i"]], tz="UTC"), "dir": "BUY" if is_buy else "SELL",
                       "entry": round(sgn * s["entry"], 2), "sl": round(sgn * s["sl"], 2),
                       "tp": round(sgn * s["tp"], 2), "risk_pips": round(s["risk"] / settings.PIP_SIZE, 1),
                       "zone": s["kind"], "R": round(r, 3), "outcome": why,
                       "exit_time": pd.Timestamp(mk.t[i], tz="UTC")})
        if r < 0:
            loss_day += 1
        state = "idle"

    def plan(entry, sl, i_entry, limit):
        """Hitung TP; return dict atau None bila risiko/RR tidak lolos."""
        risk = entry - sl
        if not (RISK_MIN <= risk <= RISK_MAX) or n_day >= MAX_TRADES_DAY or loss_day >= MAX_LOSS_DAY:
            return None
        if cfg.tp == "liq":
            tp = s["target"]
            if not np.isfinite(tp) or (tp - entry) / risk < LIQ_RR_MIN:
                return None
        else:
            tp = entry + float(cfg.tp) * risk
        return {"risk": risk, "tp": tp, "sl": sl}

    for i in range(300, n - 1):
        if mk.day[i] != day_key:
            day_key, n_day, loss_day = mk.day[i], 0, 0
        cost = spr[i] if is_buy else 0.0
        xadj = 0.0 if is_buy else spr[i]

        if state == "open":
            if i < s["entry_i"] or (i == s["entry_i"] and s["limit"]):
                continue
            if L[i] - xadj <= s["sl"]:
                close_trade(i, (s["sl"] - s["entry"]) / s["risk"], "SL")
                continue
            if H[i] - xadj >= s["tp"]:
                close_trade(i, (s["tp"] - s["entry"]) / s["risk"], "TP")
            continue

        if state == "pending":
            if L[i] + cost <= s["lim"]:
                s["entry"] = min(s["lim"], O[i] + cost)
                s["entry_i"], s["limit"] = i, True
                s["risk"] = s["entry"] - s["sl"]
                n_day += 1
                state = "open"
                if L[i] - xadj <= s["sl"]:
                    close_trade(i, (s["sl"] - s["entry"]) / s["risk"], "SL")
                continue
            if H[i] - xadj >= s["tp"] or L[i] <= s["sl"] or i > s["pend_until"]:
                state = "idle"
            continue

        while ptr < len(obs) and obs[ptr][0] <= i:
            live.append(obs[ptr])
            ptr += 1
        if i % 15 == 0 or state == "idle":
            live = [p for p in live if p[1] > i and i - p[0] <= ob_age]

        if state == "armed":
            if C[i] < s["inval"] or i - s["arm_i"] > arm_wait:
                state = "idle"
                continue
            if L[i] < s["low"]:
                s["low"], s["low_i"] = L[i], i
            lo_i = s["low_i"]
            k = next((k for k in range(lo_i - 1, max(s["arm_i"] - 60, 2), -1) if is_sh[k] and k + 2 <= i), None)
            level = H[k] if k is not None else H[max(0, s["arm_i"] - 6):s["arm_i"] + 1].max()
            if i <= lo_i or C[i] <= level:
                continue
            sl = s["low"] - SL_BUF
            if cfg.entry == "ob":
                j = next((j for j in range(lo_i, max(lo_i - 6, 0), -1) if C[j] < O[j]), None)
                if j is not None and O[j] < C[i]:
                    lim = O[j]
                    p = plan(lim, sl, None, True)
                    if p:
                        s.update(lim=lim, pend_until=i + pend_wait, **p)
                        state = "pending"
                    else:
                        state = "idle"
                    continue
            entry = O[i + 1] + (spr[i + 1] if is_buy else 0.0)
            p = plan(entry, sl, i + 1, False)
            if p:
                s.update(entry=entry, entry_i=i + 1, limit=False, **p)
                n_day += 1
                state = "open"
            else:
                state = "idle"
            continue

        # idle
        if n_day >= MAX_TRADES_DAY or loss_day >= MAX_LOSS_DAY or not bias[i]:
            continue
        if cfg.session and not (SESSION_UTC[0] <= mk.hour[i] < SESSION_UTC[1]):
            continue
        z = ote[i]
        has_ote = np.isfinite(z[0])
        cands = []      # (top, bottom, inval, target, key, kind)
        if cfg.zone in ("ote", "either") and has_ote:
            cands.append((z[0], z[1], z[2], z[3], ("ote", z[4]), "OTE"))
        if cfg.zone in ("ob", "either", "ob_ote"):
            for p in live:
                if cfg.zone == "ob_ote" and not (has_ote and p[2] >= z[1] and p[3] <= z[0]):
                    continue
                tgt = z[3] if has_ote else np.nan
                cands.append((p[2], p[3], p[3], tgt, ("ob", p), "OB_OTE" if cfg.zone == "ob_ote" else "OB"))
        best = None
        for cd in cands:
            if cd[4] in used or not (C[i - 1] > cd[0] >= L[i]) or C[i] < cd[2]:
                continue
            if best is None or cd[0] > best[0]:
                best = cd
        if best is None:
            continue
        used.add(best[4])
        s = {"arm_i": i, "low": L[i], "low_i": i, "inval": best[2], "target": best[3], "kind": best[5]}
        state = "armed"
    return trades


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ltf", default="M1", choices=("M1", "M5"))
    args = ap.parse_args()
    m1 = load_m1("M1")
    m1 = m1[m1.index >= "2025-06-16"]
    mk = Market(m1, args.ltf)
    print(f"Data {args.ltf}: {mk.df.index[0]:%Y-%m-%d} → {mk.df.index[-1]:%Y-%m-%d} ({mk.n} bar) | "
          f"OB M15 buy {len(mk.obs[True])} sell {len(mk.obs[False])}", flush=True)
    grid = [Cfg(b, z, e, tp, ses) for b, z, e, tp, ses in itertools.product(
        ("cross", "cross200"), ("ote", "ob", "either", "ob_ote"), ("market", "ob"), ("2", "3", "liq"),
        (True, False))]
    rows, all_t = [], []
    for cfg in grid:
        t = pd.DataFrame(run_side(mk, cfg, True) + run_side(mk, cfg, False))
        if t.empty:
            continue
        t["cfg"] = cfg.name
        all_t.append(t)
        tr, te = stats(t[t.time < SPLIT]), stats(t[t.time >= SPLIT])
        rows.append({"cfg": cfg.name, **{f"tr_{k}": v for k, v in tr.items()},
                     **{f"te_{k}": v for k, v in te.items()}})
    res = pd.DataFrame(rows)
    tag = args.ltf.lower()
    res.to_csv(settings.DATA_DIR / f"ote_grid_{tag}.csv", index=False)
    pd.concat(all_t).to_csv(settings.DATA_DIR / f"ote_trades_{tag}.csv", index=False)
    with pd.option_context("display.width", 260, "display.max_rows", 120):
        print(res.sort_values("tr_R", ascending=False).to_string(index=False))
        both = res[(res.tr_PF > 1.1) & (res.te_PF > 1.1) & (res.tr_trades >= 60) & (res.te_trades >= 40)]
        print(f"\nPF > 1.1 di LATIH dan UJI: {len(both)} dari {len(res)} variasi")


if __name__ == "__main__":
    main()
