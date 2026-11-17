"""
Strategi sendiri ala SMC/ICT top-down (tanpa sinyal admin), XAUUSD, eksekusi di bar M5.

    python -m tg_signal.pro_strategy            # grid variasi, latih Jun 2025–Mar 2026 vs uji Apr–Nov 2026

Alur per arah (BUY; SELL kebalikannya, dihitung di ruang harga dinegasikan):
1. Bias H4 (bar H4 terakhir yang sudah close):
   ema  : close > EMA50 dan EMA50 naik (vs 3 bar lalu)
   dc   : breakout Donchian-20 terakhir ke atas
   none : tanpa bias
2. Premium/discount (opsional): POI harus di separuh bawah range H4 (Donchian-30 high/low).
3. POI M15 (FVG / OB / IFVG dari detectors/poi.py) yang masih utuh, ukuran ≥ $0.5, umur ≤ 3 hari.
4. Sesi (opsional): setup baru hanya 07:00–16:00 UTC (14:00–23:00 WIB, London + NY pagi).
5. Sentuhan: bar M5 menyentuh tepi atas POI dari atas (close bar sebelumnya di atas POI) → "armed".
   Batal bila M5 close di bawah POI atau tidak ada konfirmasi dalam 36 bar (3 jam).
6. Sapuan likuiditas (opsional): low sejak armed menembus swing low M5 (fractal ±2) 60 bar terakhir.
7. Konfirmasi CHoCH M5: close di atas swing high M5 terakhir sebelum low terendah sejak armed.
   Filter pullback (opsional, min_pb): high tertinggi 4 jam terakhir → low terendah sesudahnya harus
   ≥ min_pb × ATR14 bias TF; pullback dangkal (harga belum benar-benar koreksi) → setup dibuang.
8. Entry: close = market di open bar berikutnya | fvg = limit di tepi atas FVG M5 terbaru pada kaki
   CHoCH (berlaku 12 bar; tanpa FVG → market).
9. SL = low terendah sejak armed − $0.3. Risiko harus 10–100 pips ($1–$10), selain itu dilewati.
   TP = entry + RR × risiko. BE (opsional): SL ke entry saat harga mencapai +1R.
10. Satu posisi per arah, maks 3 trade/hari per arah, stop setelah 2 loss/hari (hari WIB).
Harga bar = BID; BUY masuk di ask, SELL keluar di ask. SL & TP satu bar → SL. Bar fill limit: hanya cek SL.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal.detectors.poi import find_pois
from tg_signal.market_data import load_m1

SPLIT = pd.Timestamp("2026-04-01", tz="UTC")
SESSION_UTC = (7, 16)
POI_MIN = 0.5
POI_AGE = 3 * 288          # bar M5
ARM_WAIT = 36
PEND_WAIT = 12
SL_BUF = 0.3
RISK_MIN, RISK_MAX = 1.0, 10.0
MAX_TRADES_DAY, MAX_LOSS_DAY = 3, 2
PB_LOOKBACK = 48           # bar M5 (4 jam) untuk mengukur pullback: high tertinggi → low terendah sesudahnya


@dataclass(frozen=True)
class Cfg:
    bias: str = "ema"
    pd: bool = True
    sweep: bool = True
    entry: str = "fvg"
    rr: float = 2.0
    session: bool = True
    be: bool = False
    fallback: str = "market"   # kaki CHoCH tanpa FVG M5: market | level (limit retest level CHoCH) |
                               # half (limit 50% kaki CHoCH) | skip
    min_pb: float = 0.0        # pullback minimal ke POI (× ATR14 bias TF) saat CHoCH; 0 = mati


    @property
    def name(self) -> str:
        return (f"{self.bias}_{'pd' if self.pd else 'nopd'}_{'sw' if self.sweep else 'nosw'}_{self.entry}"
                f"_RR{self.rr:g}_{'ses' if self.session else 'all'}{'_BE' if self.be else ''}"
                f"{f'_pb{self.min_pb:g}' if self.min_pb else ''}")


def _htf_index(t5: np.ndarray, htf_index: pd.DatetimeIndex, minutes: int) -> np.ndarray:
    """Untuk tiap bar M5: indeks bar HTF terakhir yang sudah close saat bar M5 itu close."""
    close_htf = (htf_index + pd.Timedelta(minutes=minutes)).values.astype("datetime64[ns]")
    close_m5 = t5 + np.timedelta64(5, "m")
    return np.searchsorted(close_htf, close_m5, side="right") - 1


class Market:
    def __init__(self, df: pd.DataFrame, ema_span: int = 50, bias_tf: int = 240, min_slope: float = 0.0):
        """min_slope: EMA harus naik/turun > min_slope × ATR14 (bias TF) dalam 3 bar — tren benar-benar bergerak."""
        self.df = df
        self.t = df.index.values.astype("datetime64[ns]")
        self.n = len(df)
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.spr = df["spread"].to_numpy(float)
        self.hour = df.index.hour.to_numpy()
        self.day = (df.index + pd.Timedelta(hours=7)).date
        self.arr = {True: (o, h, l, c), False: (-o, -l, -h, -c)}

        h4 = df.resample(f"{bias_tf}min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        k = _htf_index(self.t, h4.index, bias_tf)
        valid = k >= 0
        kk = np.where(valid, k, 0)
        ema = h4["close"].ewm(span=ema_span, adjust=False).mean()
        atr = (h4["high"] - h4["low"]).rolling(14).mean()
        slope = ema.diff(3)
        self.atr_htf = np.where(valid, atr.to_numpy()[kk], np.nan)
        up = ((h4["close"] > ema) & (slope > min_slope * atr)).to_numpy()
        dn = ((h4["close"] < ema) & (slope < -min_slope * atr)).to_numpy()
        hi20, lo20 = h4["high"].rolling(20).max().shift(1), h4["low"].rolling(20).min().shift(1)
        state, st = np.zeros(len(h4)), 0
        for i, (cl, a, b) in enumerate(zip(h4["close"], hi20, lo20)):
            if cl > a:
                st = 1
            elif cl < b:
                st = -1
            state[i] = st
        mid = ((h4["high"].rolling(30).max() + h4["low"].rolling(30).min()) / 2).to_numpy()
        self.bias = {("ema", True): up[kk] & valid, ("ema", False): dn[kk] & valid,
                     ("dc", True): (state[kk] == 1) & valid, ("dc", False): (state[kk] == -1) & valid,
                     ("none", True): valid, ("none", False): valid}
        m = np.where(valid, mid[kk], np.nan)
        self.mid = {True: m, False: -m}

        m15 = df.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        to5 = np.searchsorted(self.t, (m15.index + pd.Timedelta(minutes=15)).values.astype("datetime64[ns]"),
                              side="left") - 1
        self.pois = {}
        for is_buy in (True, False):
            a = [m15[x].to_numpy(float) for x in ("open", "high", "low", "close")]
            if not is_buy:
                a = [-a[0], -a[2], -a[1], -a[3]]
            raw = find_pois(*a, min_size=POI_MIN)
            self.pois[is_buy] = [(int(to5[p.created]), int(to5[p.dead]) if p.dead < len(m15) else self.n,
                                  p.top, p.bottom, p.kind) for p in raw]
        self.frac = {}
        for is_buy, (o_, h_, l_, c_) in self.arr.items():
            sh = np.zeros(self.n, bool)
            sl = np.zeros(self.n, bool)
            hh = np.lib.stride_tricks.sliding_window_view(h_, 5).max(axis=1)
            ll = np.lib.stride_tricks.sliding_window_view(l_, 5).min(axis=1)
            sh[2:-2] = h_[2:-2] >= hh
            sl[2:-2] = l_[2:-2] <= ll
            self.frac[is_buy] = (sh, sl)


def run_side(mk: Market, cfg: Cfg, is_buy: bool, block: np.ndarray | None = None,
             final: dict | None = None) -> list[dict]:
    """Simulasi satu arah. block[i] = True → jam news: tidak cari setup / entry baru, pending dibatalkan.
    final (dict) diisi state terakhir (dipakai runner live)."""
    O, H, L, C = mk.arr[is_buy]
    spr, n = mk.spr, mk.n
    bias, mid = mk.bias[(cfg.bias, is_buy)], mk.mid[is_buy]
    is_sh, is_sl = mk.frac[is_buy]
    pois = mk.pois[is_buy]
    sgn = 1 if is_buy else -1
    trades: list[dict] = []
    live: list[tuple] = []
    ptr = 0
    used: set = set()
    state = "idle"
    day_key, n_day, loss_day = None, 0, 0
    s: dict = {}

    def close_trade(i, r, why):
        nonlocal state, n_day, loss_day
        trades.append({"time": pd.Timestamp(mk.t[s["entry_i"]], tz="UTC"), "dir": "BUY" if is_buy else "SELL",
                       "entry": round(sgn * s["entry"], 2), "sl": round(sgn * s["sl0"], 2),
                       "tp": round(sgn * s["tp"], 2), "risk_pips": round(s["risk"] / settings.PIP_SIZE, 1),
                       "poi": s["poi"][4], "R": round(r, 3), "outcome": why,
                       "exit_time": pd.Timestamp(mk.t[i], tz="UTC"),
                       "entry_i": s["entry_i"], "exit_i": i, "arm_i": s["arm_i"], "poi_created_i": s["poi"][0],
                       "poi_top": s["poi"][2], "poi_bottom": s["poi"][3], "risk_px": s["risk"]})
        if r < 0:
            loss_day += 1
        state = "idle"

    for i in range(300, n - 1):
        if mk.day[i] != day_key:
            day_key, n_day, loss_day = mk.day[i], 0, 0
        cost = spr[i] if is_buy else 0.0
        xadj = 0.0 if is_buy else spr[i]

        if state == "open":
            if i < s["entry_i"] or (i == s["entry_i"] and s["limit"]):
                continue
            if L[i] - xadj <= s["sl"]:
                close_trade(i, (s["sl"] - s["entry"]) / s["risk"], "SL" if s["sl"] < s["entry"] else "BE")
                continue
            if H[i] - xadj >= s["tp"]:
                close_trade(i, cfg.rr, "TP")
                continue
            if cfg.be and H[i] - xadj >= s["entry"] + s["risk"]:
                s["sl"] = max(s["sl"], s["entry"])
            continue

        if state == "pending":
            if block is not None and block[i]:
                state = "idle"                  # news: batalkan pending
                continue
            if L[i] + cost <= s["lim"]:
                s["entry"] = min(s["lim"], O[i] + cost)
                s["entry_i"], s["limit"] = i, True
                n_day += 1
                state = "open"
                if L[i] - xadj <= s["sl"]:
                    close_trade(i, (s["sl"] - s["entry"]) / s["risk"], "SL")
                continue
            if H[i] - xadj >= s["tp"] or L[i] <= s["sl"] or i > s["pend_until"]:
                state = "idle"
            continue

        # perbarui POI hidup
        while ptr < len(pois) and pois[ptr][0] < i:
            live.append(pois[ptr])
            ptr += 1
        live = [p for p in live if p[1] >= i and i - p[0] <= POI_AGE]

        if state == "armed":
            p = s["poi"]
            if C[i] < p[3] or i - s["arm_i"] > ARM_WAIT:
                state = "idle"
                continue
            if L[i] < s["low"]:
                s["low"], s["low_i"] = L[i], i
            swept = s["ref_low"] is not None and s["low"] < s["ref_low"]
            if cfg.sweep and not swept:
                continue
            # swing high M5 terakhir yang sudah dikenal sebelum low terendah
            lo_i = s["low_i"]
            k = next((k for k in range(lo_i - 1, max(s["arm_i"] - 40, 2), -1) if is_sh[k] and k + 2 <= i), None)
            level = H[k] if k is not None else H[max(0, s["arm_i"] - 6):s["arm_i"] + 1].max()
            if i <= lo_i or C[i] <= level:
                continue
            if block is not None and block[i]:
                continue                        # news: tunda entry
            if cfg.min_pb:
                w0 = max(0, i - PB_LOOKBACK)
                hi_i = w0 + int(np.argmax(H[w0:i + 1]))
                if not (H[hi_i] - L[hi_i:i + 1].min() >= cfg.min_pb * mk.atr_htf[i]):
                    state = "idle"              # pullback terlalu dangkal: setup dibuang
                    continue
            sl = s["low"] - SL_BUF
            if cfg.entry == "fvg":
                ks = [j for j in range(lo_i + 2, i + 1) if L[j] > H[j - 2]]
                if ks:
                    lim = L[ks[-1]]
                    risk = lim - sl
                    if RISK_MIN <= risk <= RISK_MAX and n_day < MAX_TRADES_DAY and loss_day < MAX_LOSS_DAY:
                        s.update(lim=lim, sl=sl, sl0=sl, risk=risk, tp=lim + cfg.rr * risk, pend_until=i + PEND_WAIT)
                        state = "pending"
                    else:
                        state = "idle"
                    continue
            if cfg.fallback != "market":
                if cfg.fallback == "skip":
                    state = "idle"
                    continue
                lim = level if cfg.fallback == "level" else (s["low"] + H[lo_i:i + 1].max()) / 2
                risk = lim - sl
                if RISK_MIN <= risk <= RISK_MAX and n_day < MAX_TRADES_DAY and loss_day < MAX_LOSS_DAY:
                    s.update(lim=lim, sl=sl, sl0=sl, risk=risk, tp=lim + cfg.rr * risk, pend_until=i + PEND_WAIT)
                    state = "pending"
                else:
                    state = "idle"
                continue
            entry = O[i + 1] + (spr[i + 1] if is_buy else 0.0)
            risk = entry - sl
            if RISK_MIN <= risk <= RISK_MAX and n_day < MAX_TRADES_DAY and loss_day < MAX_LOSS_DAY:
                s.update(entry=entry, entry_i=i + 1, limit=False, sl=sl, sl0=sl, risk=risk,
                         tp=entry + cfg.rr * risk)
                n_day += 1
                state = "open"
            else:
                state = "idle"
            continue

        # idle: cari POI yang baru disentuh
        if n_day >= MAX_TRADES_DAY or loss_day >= MAX_LOSS_DAY or not bias[i]:
            continue
        if block is not None and block[i]:
            continue
        if cfg.session and not (SESSION_UTC[0] <= mk.hour[i] < SESSION_UTC[1]):
            continue
        best = None
        for p in live:
            created, dead, top, bottom, kind = p
            if p in used or not (C[i - 1] > top >= L[i]) or C[i] < bottom:
                continue
            if cfg.pd and not (top <= mid[i]):
                continue
            if best is None or top > best[2]:
                best = p
        if best is None:
            continue
        used.add(best)
        ref = next((L[k] for k in range(i - 3, max(i - 60, 2), -1) if is_sl[k]), None)
        s = {"poi": best, "arm_i": i, "low": L[i], "low_i": i, "ref_low": ref}
        state = "armed"
    if final is not None:
        final.update(state=state, s=dict(s), last_i=n - 2)
    return trades


def stats(g: pd.DataFrame) -> dict:
    if g.empty:
        return {"trades": 0, "wr%": 0.0, "R": 0.0, "PF": 0.0, "maxDD_R": 0.0, "per_mgg": 0.0}
    r = g.sort_values("time")["R"]
    gw, gl = r[r > 0].sum(), -r[r < 0].sum()
    eq = r.cumsum()
    weeks = max(1.0, (g["time"].max() - g["time"].min()).days / 7)
    return {"trades": len(r), "wr%": round(100 * (r > 0).mean(), 1), "R": round(r.sum(), 1),
            "PF": round(gw / gl, 2) if gl else np.inf, "maxDD_R": round(float((eq.cummax() - eq).max()), 1),
            "per_mgg": round(len(r) / weeks, 1)}


def main() -> None:
    df = load_m1("M5")
    mk = Market(df)
    print(f"Data M5: {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d} ({mk.n} bar) | "
          f"POI M15: buy {len(mk.pois[True])}, sell {len(mk.pois[False])}")
    grid = [Cfg(b, pd_, sw, e, rr, ses, be) for b, pd_, sw, e, rr, ses, be in itertools.product(
        ("ema", "dc", "none"), (True, False), (True, False), ("fvg", "close"), (2.0, 3.0), (True, False),
        (False, True))]
    rows, all_trades = [], []
    for cfg in grid:
        t = pd.DataFrame(run_side(mk, cfg, True) + run_side(mk, cfg, False))
        if t.empty:
            continue
        t["cfg"] = cfg.name
        all_trades.append(t)
        tr, te = stats(t[t.time < SPLIT]), stats(t[t.time >= SPLIT])
        rows.append({"cfg": cfg.name, **{f"tr_{k}": v for k, v in tr.items()},
                     **{f"te_{k}": v for k, v in te.items()}})
    res = pd.DataFrame(rows)
    res.to_csv(settings.DATA_DIR / "pro_grid.csv", index=False)
    pd.concat(all_trades).to_csv(settings.DATA_DIR / "pro_trades.csv", index=False)
    with pd.option_context("display.width", 240, "display.max_rows", 80):
        print("\n20 terbaik di LATIH (total R, min 60 trade) + hasil UJI:")
        print(res[res.tr_trades >= 60].sort_values("tr_R", ascending=False).head(20).to_string(index=False))
        both = res[(res.tr_PF > 1.1) & (res.te_PF > 1.1) & (res.tr_trades >= 60) & (res.te_trades >= 40)]
        print(f"\nPF > 1.1 di LATIH dan UJI: {len(both)} dari {len(res)} variasi")
        print(both.sort_values("te_R", ascending=False).head(20).to_string(index=False))


if __name__ == "__main__":
    main()
