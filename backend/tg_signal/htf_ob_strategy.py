"""
Metode "SMC Multi-Timeframe: HTF Order Block (setelah BOS/CHoCH) → CHoCH LTF → retest OB LTF", XAUUSD.
Metode terpisah — hanya backtest.

    python -m tg_signal.htf_ob_strategy            # grid; M15: latih Sep 2022–2024 / uji 2025–Nov 2026,
                                                   #       M5 : latih Jun 2025–Mar 2026 / uji Apr–Nov 2026

Alur per arah (BUY; SELL kebalikannya, dihitung di ruang harga dinegasikan):
1. HTF (H4/H1, di-resample dari data LTF), hanya bar yang sudah close:
   swing = fractal ±2 (dikenal 2 bar kemudian). Break struktur = CLOSE di atas swing high terakhir
   yang belum ditembus (BOS bila trend sudah naik, CHoCH bila sebelumnya turun — keduanya sah).
   Bias = arah break terakhir.
   OB HTF = candle bearish terakhir sebelum kaki impuls (dicari mundur dari low terendah kaki
   swing high → bar break). Zona [low, high] candle itu. Batal bila close HTF < bawah OB,
   bias berbalik, umur > OB_AGE bar HTF, atau diganti OB baru. Tiap OB hanya dipakai sekali.
2. Retrace: bar LTF menyentuh tepi atas OB HTF → armed. Batal bila close LTF < bawah OB HTF
   atau tidak ada CHoCH dalam ARM_WAIT jam.
3. CHoCH LTF: close di atas swing high LTF (fractal ±2) terakhir sebelum low terendah sejak armed.
4. OB LTF: candle bearish terakhir sebelum kaki impuls (mundur ≤ 10 bar dari low terendah).
   Entry limit (retest) di: top = high OB | open = open OB (badan) | mid = tengah OB.
   Berlaku PEND_WAIT jam; batal bila harga ke TP dulu / close < SL / bias HTF berbalik.
5. SL = low OB LTF − buffer ("ob") atau low terendah sejak armed − buffer ("swing").
   TP = RR × risiko. Risiko RISK_MIN–RISK_MAX.
Varian tambahan: entry "market" (open bar sesudah CHoCH, tanpa retest); reuse = OB HTF boleh dipakai
berkali-kali selama valid; filt "ema" = EMA50 H1 searah & miring > 0.1 ATR/3 bar saat CHoCH, "ema_pb" =
ditambah pullback 4 jam terakhir >= 1 ATR14 H1 (filter yang sama dengan pro_live).
Harga bar = BID; BUY masuk di ask, SELL keluar di ask. Bar fill: hanya cek SL. SL & TP satu bar → SL.
"""
from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal.market_data import load_m1
from tg_signal.pro_strategy import stats

OB_AGE = 30                    # bar HTF
ARM_WAIT_H = 24
PEND_WAIT_H = 12
SL_BUF = 0.3                   # $
RISK_MIN, RISK_MAX = 1.0, 15.0
OB_LOOK = 10
MIN_SLOPE = 0.1                # sama dengan pro_live
MIN_PB = 1.0                   # × ATR14 H1, pullback 4 jam terakhir (sama dengan pro_live)
SPLITS = {"M15": pd.Timestamp("2025-01-01", tz="UTC"), "M5": pd.Timestamp("2026-04-01", tz="UTC")}


@dataclass(frozen=True)
class Cfg:
    htf: str = "H4"
    entry: str = "top"         # top | open | mid | market (open bar sesudah CHoCH, tanpa retest)
    sl: str = "ob"             # ob | swing
    rr: float = 2.0
    reuse: bool = False        # OB HTF boleh dipakai berkali-kali selama masih valid
    filt: str = "none"         # none | ema (EMA50 H1 searah & miring > MIN_SLOPE ATR) | ema_pb (+ pullback ≥ MIN_PB ATR H1)

    @property
    def name(self) -> str:
        return (f"{self.htf}_{self.entry}_{self.sl}_RR{self.rr:g}"
                f"{'_re' if self.reuse else ''}{'' if self.filt == 'none' else '_' + self.filt}")


def _fractals(h: np.ndarray, l: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = len(h)
    sh, sl = np.zeros(n, bool), np.zeros(n, bool)
    hh = np.lib.stride_tricks.sliding_window_view(h, 5).max(axis=1)
    ll = np.lib.stride_tricks.sliding_window_view(l, 5).min(axis=1)
    sh[2:-2] = h[2:-2] >= hh
    sl[2:-2] = l[2:-2] <= ll
    return sh, sl


def htf_structure(o, h, l, c) -> np.ndarray:
    """Per bar HTF k (close): [bias_up(1/0), ob_top, ob_bot, ob_id] untuk sisi BUY (NaN bila tidak ada OB)."""
    n = len(c)
    sh, sl = _fractals(h, l)
    out = np.full((n, 4), np.nan)
    out[:, 0] = 0
    hi_sw = lo_sw = None          # [idx, price, broken]
    bias = 0
    ob = None
    for k in range(n):
        j = k - 2
        if j >= 2:
            if sh[j]:
                hi_sw = [j, h[j], False]
            if sl[j]:
                lo_sw = [j, l[j], False]
        if hi_sw and not hi_sw[2] and c[k] > hi_sw[1]:
            hi_sw[2] = True
            bias = 1
            seg = l[hi_sw[0]:k + 1]
            lo_i = hi_sw[0] + int(np.argmin(seg))
            jb = next((x for x in range(lo_i, max(lo_i - OB_LOOK, hi_sw[0] - 1), -1) if c[x] < o[x]), None)
            ob = [h[jb], l[jb], float(k)] if jb is not None else None
        if lo_sw and not lo_sw[2] and c[k] < lo_sw[1]:
            lo_sw[2] = True
            bias = -1
            ob = None
        if ob is not None and (c[k] < ob[1] or k - ob[2] > OB_AGE):
            ob = None
        out[k, 0] = 1 if bias == 1 else 0
        if ob is not None:
            out[k, 1:] = ob
    return out


class Market:
    def __init__(self, df: pd.DataFrame, ltf: str):
        self.ltf = ltf
        self.bar_min = 15 if ltf == "M15" else 5
        self.df = df
        self.t = df.index.values.astype("datetime64[ns]")
        self.n = len(df)
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.spr = df["spread"].to_numpy(float)
        self.arr = {True: (o, h, l, c), False: (-o, -l, -h, -c)}
        self.frac = {b: _fractals(a[1], a[2]) for b, a in self.arr.items()}
        h1 = df.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        k1 = np.searchsorted((h1.index + pd.Timedelta("1h")).values.astype("datetime64[ns]"),
                             self.t + np.timedelta64(self.bar_min, "m"), side="right") - 1
        ok1, kk1 = k1 >= 0, np.where(k1 >= 0, k1, 0)
        ema = h1["close"].ewm(span=50, adjust=False).mean()
        atr = (h1["high"] - h1["low"]).rolling(14).mean()
        slope = ema.diff(3)
        up = ((h1["close"] > ema) & (slope > MIN_SLOPE * atr)).to_numpy()
        dn = ((h1["close"] < ema) & (slope < -MIN_SLOPE * atr)).to_numpy()
        self.ema_ok = {True: up[kk1] & ok1, False: dn[kk1] & ok1}
        self.atr_h1 = np.where(ok1, atr.to_numpy()[kk1], np.nan)
        self.htf = {}
        for htf, rule in (("H4", "4h"), ("H1", "1h")):
            hd = df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            close_t = (hd.index + pd.Timedelta(rule)).values.astype("datetime64[ns]")
            k = np.searchsorted(close_t, self.t + np.timedelta64(self.bar_min, "m"), side="right") - 1
            a = [hd[x].to_numpy(float) for x in ("open", "high", "low", "close")]
            for is_buy in (True, False):
                aa = a if is_buy else [-a[0], -a[2], -a[1], -a[3]]
                st = htf_structure(*aa)
                z = np.full((self.n, 4), np.nan)
                z[:, 0] = 0
                z[k >= 0] = st[k[k >= 0]]
                self.htf[(htf, is_buy)] = z


def run_side(mk: Market, cfg: Cfg, is_buy: bool) -> list[dict]:
    O, H, L, C = mk.arr[is_buy]
    spr, n = mk.spr, mk.n
    st = mk.htf[(cfg.htf, is_buy)]
    is_sh, _ = mk.frac[is_buy]
    sgn = 1 if is_buy else -1
    per_h = 60 // mk.bar_min
    arm_wait, pend_wait = ARM_WAIT_H * per_h, PEND_WAIT_H * per_h
    trades: list[dict] = []
    used: set = set()
    state = "idle"
    s: dict = {}
    busy_i = -9

    def close_trade(i, r, why):
        nonlocal state
        trades.append({"time": pd.Timestamp(mk.t[s["entry_i"]], tz="UTC"), "dir": "BUY" if is_buy else "SELL",
                       "entry": round(sgn * s["entry"], 2), "sl": round(sgn * s["sl"], 2),
                       "tp": round(sgn * s["tp"], 2), "risk_pips": round(s["risk"] / settings.PIP_SIZE, 1),
                       "R": round(r, 3), "outcome": why, "exit_time": pd.Timestamp(mk.t[i], tz="UTC"),
                       "arm_time": pd.Timestamp(mk.t[s["arm_i"]], tz="UTC")})
        state = "idle"

    for i in range(60, n - 1):
        if state != "idle":
            busy_i = i
        cost = spr[i] if is_buy else 0.0
        xadj = 0.0 if is_buy else spr[i]

        if state == "open":
            if i == s["entry_i"]:
                if L[i] - xadj <= s["sl"]:
                    close_trade(i, (s["sl"] - s["entry"]) / s["risk"], "SL")
                continue
            if L[i] - xadj <= s["sl"]:
                close_trade(i, (s["sl"] - s["entry"]) / s["risk"], "SL")
            elif H[i] - xadj >= s["tp"]:
                close_trade(i, (s["tp"] - s["entry"]) / s["risk"], "TP")
            continue

        if state == "pending":
            if L[i] + cost <= s["lim"]:
                s["entry"] = min(s["lim"], O[i] + cost)
                s["risk"] = s["entry"] - s["sl"]
                s["entry_i"] = i
                state = "open"
                if L[i] - xadj <= s["sl"]:
                    close_trade(i, (s["sl"] - s["entry"]) / s["risk"], "SL")
                continue
            if H[i] - xadj >= s["tp"] or C[i] < s["sl"] or i > s["pend_until"] or st[i, 0] != 1:
                state = "idle"
            continue

        if state == "armed":
            if C[i] < s["inval"] or i - s["arm_i"] > arm_wait or st[i, 0] != 1:
                state = "idle"
                continue
            if L[i] < s["low"]:
                s["low"], s["low_i"] = L[i], i
            lo_i = s["low_i"]
            k = next((k for k in range(lo_i - 1, max(lo_i - 100, 2), -1) if is_sh[k] and k + 2 <= i), None)
            if k is None or i <= lo_i or C[i] <= H[k]:
                continue
            # CHoCH LTF terkonfirmasi (close). Filter, lalu cari OB LTF.
            if cfg.filt != "none" and not mk.ema_ok[is_buy][i]:
                state = "idle"
                continue
            if cfg.filt == "ema_pb":
                w0 = max(0, i - 4 * per_h)
                hi_i = w0 + int(np.argmax(H[w0:i + 1]))
                if not (H[hi_i] - L[hi_i:i + 1].min() >= MIN_PB * mk.atr_h1[i]):
                    state = "idle"
                    continue
            j = next((x for x in range(lo_i, max(lo_i - OB_LOOK, 0), -1) if C[x] < O[x]), None)
            if j is None:
                state = "idle"
                continue
            sl = (L[j] if cfg.sl == "ob" else s["low"]) - SL_BUF
            if cfg.entry == "market":
                entry = O[i + 1] + (spr[i + 1] if is_buy else 0.0)
                risk = entry - sl
                if not (RISK_MIN <= risk <= RISK_MAX):
                    state = "idle"
                    continue
                s.update(entry=entry, sl=sl, risk=risk, tp=entry + cfg.rr * risk, entry_i=i + 1)
                state = "open"
                continue
            lim = {"top": H[j], "open": O[j], "mid": (H[j] + L[j]) / 2}[cfg.entry]
            risk = lim - sl
            if not (RISK_MIN <= risk <= RISK_MAX) or lim >= C[i]:
                state = "idle"
                continue
            s.update(lim=lim, sl=sl, tp=lim + cfg.rr * risk, pend_until=i + pend_wait)
            state = "pending"
            continue

        # idle: tunggu retrace ke OB HTF
        if st[i, 0] != 1 or not np.isfinite(st[i, 1]):
            continue
        top, bot, oid = st[i, 1], st[i, 2], st[i, 3]
        if (not cfg.reuse and oid in used) or L[i] > top or C[i] < bot:
            continue
        if cfg.reuse and s.get("oid") == oid and busy_i >= i - 1:
            continue           # baru saja selesai di OB ini; tunggu bar berikutnya
        used.add(oid)
        s = {"arm_i": i, "low": L[i], "low_i": i, "inval": bot, "oid": oid}
        state = "armed"
    return trades


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ltf", nargs="+", default=["M15", "M5"])
    args = ap.parse_args()
    grid = [Cfg(h, e, s, rr, re_, f) for h, e, s, rr, re_, f in itertools.product(
        ("H4", "H1"), ("top", "open", "market"), ("ob", "swing"), (2.0, 3.0), (False, True),
        ("none", "ema", "ema_pb"))]
    rows, all_t = [], []
    for ltf in args.ltf:
        mk = Market(load_m1(ltf), ltf)
        split = SPLITS[ltf]
        print(f"Data {ltf}: {mk.df.index[0]:%Y-%m-%d} → {mk.df.index[-1]:%Y-%m-%d} ({mk.n} bar), "
              f"split {split:%Y-%m-%d}", flush=True)
        for cfg in grid:
            t = pd.DataFrame(run_side(mk, cfg, True) + run_side(mk, cfg, False))
            if t.empty:
                continue
            t["cfg"], t["ltf"] = cfg.name, ltf
            all_t.append(t)
            tr, te = stats(t[t.time < split]), stats(t[t.time >= split])
            rows.append({"ltf": ltf, "cfg": cfg.name, "risk_med": round(t.risk_pips.median()),
                         **{f"tr_{k}": v for k, v in tr.items()}, **{f"te_{k}": v for k, v in te.items()}})
    res = pd.DataFrame(rows)
    res.to_csv(settings.DATA_DIR / "htf_ob_grid.csv", index=False)
    pd.concat(all_t).to_csv(settings.DATA_DIR / "htf_ob_trades.csv", index=False)
    with pd.option_context("display.width", 260, "display.max_rows", 120):
        print(res.sort_values("tr_R", ascending=False).head(30).to_string(index=False))
        both = res[(res.tr_PF > 1.1) & (res.te_PF > 1.1) & (res.tr_trades >= 40) & (res.te_trades >= 30)]
        print(f"\nPF > 1.1 di LATIH dan UJI: {len(both)} dari {len(res)} variasi")
        print(both.sort_values("te_R", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
