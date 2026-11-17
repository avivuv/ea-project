"""
Strategi sesi XAUUSD di bar M1 (hanya backtest):
  SWEEP    — sapuan likuiditas level sesi lalu berbalik (ide 1)
  BREAKOUT — breakout range Asia (ide 3)

    python -m tg_signal.session_sweep            # grid kedua strategi, latih < Apr 2026 / uji ≥ Apr 2026

Waktu UTC (WIB = UTC+7). Range Asia = 00:00–07:00 UTC (07:00–14:00 WIB).
Jendela setup: london 07:00–10:00, ny 12:30–15:30 UTC. Posisi ditutup paksa 21:00 UTC.
Level: asia = high/low range Asia hari ini, pd = high/low hari UTC sebelumnya, both = keduanya.

SWEEP (contoh BUY di level low; SELL kebalikannya):
  1. Low bar menembus level − $0.3 (breach) di jendela setup.
  2. Dalam 15 bar close kembali di atas level (reclaim); bila tidak → batal.
  3. CHoCH: close di atas swing high M1 (fractal ±2) terakhir sebelum low ekstrem (cadangan: high
     tertinggi 10 bar sebelum ekstrem), maks 30 bar setelah reclaim; close di bawah level → batal.
  4. Entry market = open bar berikutnya | retest = limit di level (berlaku 30 bar).
  5. SL = low ekstrem − $0.3. TP = RR × risiko, atau range = sisi seberang (high Asia / high hari lalu),
     dilewati bila RR ke target < 1.5. Risiko 0.15–1.5 × ATR14 H1 (min $1). Satu trade per level per hari.
BREAKOUT (contoh BUY):
  1. Range Asia lebar 1–8 × ATR14 H1. Close M1 pertama di atas high Asia + $0.1 di jendela setup.
  2. Entry market = open bar berikutnya | retest = limit di high Asia (berlaku 60 bar).
  3. SL = tengah range (mid) atau low Asia (opp), risiko 0.3–3 × ATR14 H1. TP = RR × risiko. Satu trade per arah per hari.
Filter bias (opsional): with = EMA50 H1 searah dan miring > 0.1 ATR (sama seperti pro_live).
Harga bar = BID; BUY masuk di ask, SELL keluar di ask. SL & TP satu bar → SL. Bar fill limit: hanya SL.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal.market_data import load_m1

SPLIT = pd.Timestamp("2026-04-01", tz="UTC")
WINDOWS = {"london": (7 * 60, 10 * 60), "ny": (12 * 60 + 30, 15 * 60 + 30)}
EXIT_MIN = 21 * 60
SWEEP_MIN, SL_BUF = 0.3, 0.3
RECLAIM_WAIT, CHOCH_WAIT, RETEST_WAIT, BO_RETEST_WAIT = 15, 30, 30, 60
RISK_MIN = 1.0                          # $ absolut (spread)
RISK_ATR = (0.15, 1.5)                  # risiko sweep dalam × ATR14 H1
BO_RISK_ATR = (0.3, 3.0)                # risiko breakout dalam × ATR14 H1
RANGE_ATR = (1.0, 8.0)                  # lebar range Asia dalam × ATR14 H1
LIQ_RR_MIN = 1.5


@dataclass(frozen=True)
class Cfg:
    kind: str                 # SWEEP | BREAKOUT
    window: str               # london | ny | both
    level: str = "asia"       # SWEEP: asia | pd | both
    entry: str = "market"     # market | retest
    tp: str = "2"             # angka RR | range (SWEEP)
    sl: str = "mid"           # BREAKOUT: mid | opp
    bias: str = "none"        # none | with

    @property
    def name(self) -> str:
        lv = self.level if self.kind == "SWEEP" else f"SL{self.sl}"
        return f"{self.kind}_{self.window}_{lv}_{self.entry}_TP{self.tp}_{self.bias}"


class Data:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.t = df.index.values.astype("datetime64[ns]")
        self.n = len(df)
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.spr = df["spread"].to_numpy(float)
        self.arr = {True: (o, h, l, c), False: (-o, -l, -h, -c)}
        self.mins = np.asarray(df.index.hour * 60 + df.index.minute)
        days = df.index.normalize()
        self.day_start = {}
        uniq, first = np.unique(days.values, return_index=True)
        bounds = list(first) + [self.n]
        self.days = [(pd.Timestamp(u, tz="UTC"), bounds[k], bounds[k + 1]) for k, u in enumerate(uniq)]
        # fractal ±2
        self.sh = {}
        for b, (_, h_, l_, _) in self.arr.items():
            sh = np.zeros(self.n, bool)
            hh = np.lib.stride_tricks.sliding_window_view(h_, 5).max(axis=1)
            sh[2:-2] = h_[2:-2] >= hh
            self.sh[b] = sh
        # bias EMA50 H1 + slope (bar H1 terakhir yang sudah close)
        h1 = df.resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        ema = h1.close.ewm(span=50, adjust=False).mean()
        atr = (h1.high - h1.low).rolling(14).mean()
        slope = ema.diff(3)
        up = ((h1.close > ema) & (slope > 0.1 * atr)).to_numpy()
        dn = ((h1.close < ema) & (slope < -0.1 * atr)).to_numpy()
        close_h1 = (h1.index + pd.Timedelta(minutes=60)).values.astype("datetime64[ns]")
        k = np.searchsorted(close_h1, self.t + np.timedelta64(1, "m"), side="right") - 1
        ok = k >= 0
        kk = np.where(ok, k, 0)
        self.bias = {True: up[kk] & ok, False: dn[kk] & ok}
        self.atr = np.where(ok, atr.to_numpy()[kk], np.nan)


def simulate(d: Data, is_buy: bool, start: int, end: int, entry: float | None, lim: float | None,
             sl: float, tp: float, lim_wait: int):
    """Mulai di bar start. entry != None → market (sudah termasuk spread); lim → limit order.
    Return (entry_i, exit_i, entry, R, outcome) atau None bila limit tidak terisi."""
    O, H, L, C = d.arr[is_buy]
    spr = d.spr
    j = start
    if entry is None:
        filled = False
        while j < min(end, start + lim_wait):
            cost = spr[j] if is_buy else 0.0
            xadj = 0.0 if is_buy else spr[j]
            if H[j] - xadj >= tp:
                return None                                  # target tercapai sebelum retest
            if L[j] + cost <= lim:
                entry = min(lim, O[j] + cost)
                filled = True
                if L[j] - xadj <= sl:
                    return j, j, entry, (sl - entry) / (entry - sl) if entry > sl else -1.0, "SL"
                break
            j += 1
        if not filled:
            return None
        e = j
        j += 1
    else:
        e = start
    risk = entry - sl
    if risk <= 0:
        return None
    while j < end:
        xadj = 0.0 if is_buy else spr[j]
        if L[j] - xadj <= sl:
            return e, j, entry, (sl - entry) / risk, "SL"
        if H[j] - xadj >= tp:
            return e, j, entry, (tp - entry) / risk, "TP"
        j += 1
    j = end - 1
    xadj = 0.0 if is_buy else spr[j]
    return e, j, entry, (C[j] - xadj - entry) / risk, "TIME"


def _windows(cfg: Cfg) -> list[str]:
    return ["london", "ny"] if cfg.window == "both" else [cfg.window]


def run(d: Data, cfg: Cfg) -> pd.DataFrame:
    out = []
    prev = None
    for day, a, b in d.days:
        if b - a < 600:
            prev = (a, b)
            continue
        mins = d.mins[a:b]
        asia = np.flatnonzero(mins < 7 * 60) + a
        exit_end = a + int(np.searchsorted(mins, EXIT_MIN))
        if len(asia) < 300:
            prev = (a, b)
            continue
        for is_buy in (True, False):
            O, H, L, C = d.arr[is_buy]
            sgn = 1 if is_buy else -1
            a_lo, a_hi = L[asia].min(), H[asia].max()       # ruang BUY: lo = level sweep, hi = target
            if cfg.kind == "SWEEP":
                levels = []
                if cfg.level in ("asia", "both"):
                    levels.append(("asia", a_lo, a_hi))
                if cfg.level in ("pd", "both") and prev is not None:
                    levels.append(("pd", L[prev[0]:prev[1]].min(), H[prev[0]:prev[1]].max()))
                for lvname, lv, target in levels:
                    for w in _windows(cfg):
                        r = _sweep(d, cfg, is_buy, a, b, mins, lv, target, w, exit_end)
                        if r:
                            out.append(r | {"level": lvname, "window": w, "dir": "BUY" if is_buy else "SELL"})
                            break                                     # satu trade per level per hari
            else:
                rng = a_hi - a_lo
                atr7 = d.atr[asia[-1]]
                if not (RANGE_ATR[0] * atr7 <= rng <= RANGE_ATR[1] * atr7):
                    continue
                for w in _windows(cfg):
                    r = _breakout(d, cfg, is_buy, a, mins, a_hi, a_lo, w, exit_end)
                    if r:
                        out.append(r | {"window": w, "dir": "BUY" if is_buy else "SELL"})
                        break
        prev = (a, b)
    t = pd.DataFrame(out)
    if t.empty:
        return t
    t["time"] = pd.to_datetime(d.t[t.entry_i]).tz_localize("UTC")
    return t.sort_values("time").reset_index(drop=True)


def _sweep(d, cfg, is_buy, a, b, mins, lv, target, w, exit_end):
    O, H, L, C = d.arr[is_buy]
    w0, w1 = WINDOWS[w]
    i0, i1 = a + int(np.searchsorted(mins, w0)), a + int(np.searchsorted(mins, w1))
    sh = d.sh[is_buy]
    i = i0
    while i < i1:
        if L[i] > lv - SWEEP_MIN or C[i - 1] < lv:
            i += 1
            continue
        # breach dari atas level
        ext, ext_i = L[i], i
        j, rec = i, None
        while j < min(i + RECLAIM_WAIT, exit_end):
            if L[j] < ext:
                ext, ext_i = L[j], j
            if C[j] > lv:
                rec = j
                break
            j += 1
        if rec is None:
            i = j + 1
            continue
        k = next((k for k in range(ext_i - 1, max(ext_i - 30, a), -1) if sh[k] and k + 2 <= rec), None)
        level = H[k] if k is not None else H[max(a, ext_i - 10):ext_i + 1].max()
        level = max(level, lv)
        j, ch = rec, None
        while j < min(rec + CHOCH_WAIT, exit_end - 1):
            if L[j] < ext:
                ext = L[j]
            if C[j] < lv and j > rec:
                break
            if C[j] > level:
                ch = j
                break
            j += 1
        if ch is None:
            i = j + 1
            continue
        if cfg.bias == "with" and not d.bias[is_buy][ch]:
            return None
        sl = ext - SL_BUF
        return _plan(d, cfg, is_buy, ch, sl, target, lv, exit_end, RISK_ATR, RETEST_WAIT)
    return None


def _breakout(d, cfg, is_buy, a, mins, hi, lo, w, exit_end):
    O, H, L, C = d.arr[is_buy]
    w0, w1 = WINDOWS[w]
    i0, i1 = a + int(np.searchsorted(mins, w0)), a + int(np.searchsorted(mins, w1))
    for i in range(i0, i1):
        if C[i] > hi + 0.1:
            if cfg.bias == "with" and not d.bias[is_buy][i]:
                return None
            sl = (hi + lo) / 2 if cfg.sl == "mid" else lo
            return _plan(d, cfg, is_buy, i, sl, None, hi, exit_end, BO_RISK_ATR, BO_RETEST_WAIT)
        if C[i] < lo:          # sudah jebol ke arah lain lebih dulu: arah ini masih boleh, lanjut
            continue
    return None


def _plan(d, cfg, is_buy, i, sl, target, retest_px, exit_end, risk_atr, wait):
    O = d.arr[is_buy][0]
    if i + 1 >= exit_end:
        return None
    if cfg.entry == "market":
        entry = O[i + 1] + (d.spr[i + 1] if is_buy else 0.0)
        ref = entry
    else:
        entry, ref = None, retest_px
    risk = ref - sl
    atr = d.atr[i]
    if not np.isfinite(atr) or not (max(RISK_MIN, risk_atr[0] * atr) <= risk <= risk_atr[1] * atr):
        return None
    if cfg.tp == "range":
        if target is None or (target - ref) / risk < LIQ_RR_MIN:
            return None
        tp = target
    else:
        tp = ref + float(cfg.tp) * risk
    r = simulate(d, is_buy, i + 1, exit_end, entry, None if entry is not None else retest_px, sl, tp, wait)
    if r is None:
        return None
    e, x, ent, R, why = r
    sgn = 1 if is_buy else -1
    return {"entry_i": e, "exit_i": x, "entry": round(sgn * ent, 2), "sl": round(sgn * sl, 2),
            "tp": round(sgn * tp, 2), "risk_pips": round((ent - sl) / settings.PIP_SIZE, 1),
            "R": round(R, 3), "outcome": why}


def stats(g: pd.DataFrame) -> dict:
    if g.empty:
        return {"n": 0, "wr%": 0.0, "R": 0.0, "PF": 0.0, "DD": 0.0}
    r = g.sort_values("time")["R"]
    eq = r.cumsum()
    gl = -r[r < 0].sum()
    return {"n": len(r), "wr%": round(100 * (r > 0).mean(), 1), "R": round(r.sum(), 1),
            "PF": round(r[r > 0].sum() / gl, 2) if gl else np.inf, "DD": round(float((eq.cummax() - eq).max()), 1)}


def grid() -> list[Cfg]:
    g = [Cfg("SWEEP", w, lv, e, tp, "mid", bi) for w, lv, e, tp, bi in itertools.product(
        ("london", "ny", "both"), ("asia", "pd", "both"), ("market", "retest"), ("2", "3", "range"),
        ("none", "with"))]
    g += [Cfg("BREAKOUT", w, "asia", e, tp, sl, bi) for w, e, tp, sl, bi in itertools.product(
        ("london", "ny", "both"), ("market", "retest"), ("1.5", "2", "3"), ("mid", "opp"), ("none", "with"))]
    return g


def main() -> None:
    df = load_m1("M1")
    df = df[df.index >= "2025-06-16"]
    d = Data(df)
    print(f"Data M1 {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d} | {len(d.days)} hari", flush=True)
    rows, allt = [], []
    for cfg in grid():
        t = run(d, cfg)
        if t.empty:
            continue
        t["cfg"] = cfg.name
        allt.append(t)
        tr, te = stats(t[t.time < SPLIT]), stats(t[t.time >= SPLIT])
        rows.append({"cfg": cfg.name, "kind": cfg.kind, "risk_med": t.risk_pips.median(),
                     **{f"tr_{k}": v for k, v in tr.items()}, **{f"te_{k}": v for k, v in te.items()}})
    res = pd.DataFrame(rows)
    res.to_csv(settings.DATA_DIR / "session_grid.csv", index=False)
    pd.concat(allt).to_csv(settings.DATA_DIR / "session_trades.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_rows", 200):
        for kind in ("SWEEP", "BREAKOUT"):
            g = res[res.kind == kind]
            print(f"\n=== {kind}: {len(g)} variasi | median PF latih {g.tr_PF.median():.2f} uji {g.te_PF.median():.2f}")
            print(g.sort_values("tr_R", ascending=False).head(15).drop(columns="kind").to_string(index=False))
            ok = g[(g.tr_PF > 1.15) & (g.te_PF > 1.15) & (g.tr_n >= 50) & (g.te_n >= 40)]
            print(f"PF > 1.15 latih & uji (n ≥ 50/40): {len(ok)}")
            if len(ok):
                print(ok.sort_values("te_R", ascending=False).drop(columns="kind").to_string(index=False))


if __name__ == "__main__":
    main()
