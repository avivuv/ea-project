"""
Tes (1) POI di timeframe lebih besar (M5/M15) dengan SL di bawah POI & TP berbasis R:R, dan
(2) TP/SL tidak simetris / TP parsial untuk entry market. Simulasi tetap di bar M1.

    python -m tg_signal.wide_backtest

Asumsi sama dengan backtest_tg.py (harga bar = BID, BUY bayar spread saat masuk, SELL saat keluar,
SL & TP di bar yang sama → SL, di bar fill limit hanya SL yang dicek). Data latih Agu–Sep, uji Okt–Nov.
Selain pips, dilaporkan R (pips / risiko) karena SL tiap trade berbeda pada mode POI.
Parsial: separuh ditutup di TP1, SL sisa pindah ke entry (BE), sisa ke TP akhir. Pips = rata-rata 2 bagian.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal.backtest_tg import Bars, load_signals
from tg_signal.detectors.poi import POI, active_pois, find_pois
from tg_signal.market_data import load_m1
from tg_signal.price_resolver import resolve_zone
from tg_signal.store import Store

PIP = settings.PIP_SIZE
HORIZON = 2 * 1440
SPLIT = pd.Timestamp("2026-10-01", tz="UTC")
SL_BUF = 0.5
SL_MAX_PIPS = 100
TF_CFG = {1: (0.5, 240), 5: (1.0, 720), 15: (1.5, 1440)}   # tf: (toleransi zona $, umur maks bar M1)


@dataclass(frozen=True)
class V:
    entry: str            # MARKET | POI
    tf: int = 1           # timeframe POI (menit)
    sl: str = "fix"       # fix | poi
    sl_pips: float = 30
    tp: str = "pips"      # pips | rr
    tp_val: float = 30    # pips atau kelipatan risiko
    partial: float = 0    # >0: TP1 (pips) untuk separuh posisi, lalu BE
    exp_pips: float = 30

    @property
    def name(self) -> str:
        e = "MARKET" if self.entry == "MARKET" else f"POI_M{self.tf}_X{self.exp_pips:g}"
        sl = f"SL{self.sl_pips:g}" if self.sl == "fix" else "SLpoi"
        tp = f"TP{self.tp_val:g}" if self.tp == "pips" else f"RR{self.tp_val:g}"
        pt = f"_part{self.partial:g}BE" if self.partial else ""
        return f"{e}_{sl}_{tp}{pt}"


def tf_pois(bars: Bars, tf: int, is_buy: bool) -> list[POI]:
    """POI dari bar TF, indeks created/dead dipetakan ke bar M1 terakhir di dalam bar TF itu."""
    if tf == 1:
        o, h, l, c = bars.o, bars.h, bars.l, bars.c
        return find_pois(o, h, l, c) if is_buy else find_pois(-o, -l, -h, -c)
    r = bars.df.resample(f"{tf}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    o, h, l, c = (r[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    raw = find_pois(o, h, l, c, min_size=0.3) if is_buy else find_pois(-o, -l, -h, -c, min_size=0.3)
    close_t = (r.index + pd.Timedelta(minutes=tf)).values.astype("datetime64[ns]")
    m1 = np.searchsorted(bars.t, close_t, side="left") - 1      # bar M1 terakhir di bar TF
    n = len(r)
    return [POI(p.kind, p.top, p.bottom, int(m1[p.created]),
                int(m1[p.dead]) if p.dead < n else bars.n) for p in raw]


def simulate(sig, v: V, bars: Bars, arr: dict, pois: dict) -> dict:
    res = {"time": sig.time, "variant": v.name, "outcome": "", "pips": np.nan, "R": np.nan}
    s = bars.first_bar_after(sig.time)
    if s <= 0 or s >= bars.n:
        res["outcome"] = "NO_DATA"
        return res
    zone = resolve_zone(sig.direction, sig.level_first, sig.level_last, ref=bars.o[s - 1])
    if zone.distance > settings.TG_MAX_ZONE_DISTANCE:
        res["outcome"] = "REJECTED_DISTANCE"
        return res
    is_buy = sig.direction == "BUY"
    sgn = 1 if is_buy else -1
    O, H, L, C = arr[is_buy]
    spr = bars.spr
    zero, last = sgn * zone.zero, sgn * zone.last
    end = min(bars.n, s + HORIZON)
    exp_tp, exp_sl = zero + v.exp_pips * PIP, last - sig.sl_pips * PIP

    def plan(entry, bottom):
        sl = entry - v.sl_pips * PIP if v.sl == "fix" else bottom - SL_BUF
        sl = max(sl, entry - SL_MAX_PIPS * PIP)
        risk = entry - sl
        tp = entry + (v.tp_val * PIP if v.tp == "pips" else v.tp_val * risk)
        return sl, tp, risk

    pos = None
    if v.entry == "MARKET":
        entry = O[s] + (spr[s] if is_buy else 0.0)
        sl, tp, risk = plan(entry, 0.0)
        pos = [s, entry, sl, tp, risk, False]
    else:
        tol, age = TF_CFG[v.tf]
        lo, hi = last - tol, zero + tol
        cands = [p for p in pois[(v.tf, is_buy)] if s - age <= p.created < end and lo <= p.top <= hi]
        touched = False
    half_done = None
    for j in range(s, end):
        cost = spr[j] if is_buy else 0.0
        xadj = 0.0 if is_buy else spr[j]
        if pos is None:
            if not touched and L[j] + cost <= zero:
                touched = True
            act = active_pois(cands, j, lo, hi, age)
            if act:
                p = max(act, key=lambda z: z.top)
                if L[j] + cost <= p.top:
                    entry = min(p.top, O[j] + cost)
                    sl, tp, risk = plan(entry, p.bottom)
                    pos = [j, entry, sl, tp, risk, True]
                    if L[j] - xadj <= sl:
                        return _done(res, (sl - entry) / PIP, risk, "SL")
                    continue
            if touched and H[j] >= exp_tp:
                res["outcome"] = "EXPIRED_TP"
                return res
            if touched and L[j] <= exp_sl:
                res["outcome"] = "EXPIRED_SL"
                return res
            continue
        k0, entry, sl, tp, risk, limit = pos
        if j == k0 and limit:
            continue
        if L[j] - xadj <= sl:
            leg = (sl - entry) / PIP
            pips = leg if half_done is None else (half_done + leg) / 2
            return _done(res, pips, risk, "SL" if half_done is None else "TP1_BE")
        if v.partial and half_done is None and H[j] - xadj >= entry + v.partial * PIP:
            half_done = v.partial
            pos[2] = sl = entry                          # sisa: SL ke BE
        if H[j] - xadj >= tp:
            pips = (tp - entry) / PIP
            return _done(res, pips if half_done is None else (half_done + pips) / 2, risk, "TP")
    if pos is None:
        res["outcome"] = "NOT_FILLED"
        return res
    leg = (C[end - 1] - (0.0 if is_buy else spr[end - 1]) - pos[1]) / PIP
    return _done(res, leg if half_done is None else (half_done + leg) / 2, pos[4], "TIMEOUT")


def _done(res, pips, risk, outcome) -> dict:
    res["outcome"], res["pips"] = outcome, round(pips, 1)
    res["R"] = round(pips * PIP / risk, 3) if risk > 0 else np.nan
    res["risk_pips"] = round(risk / PIP, 1)
    return res


def variants() -> list[V]:
    vs = [V("MARKET", sl_pips=sl, tp_val=tp) for sl, tp in
          ((30, 30), (30, 45), (30, 60), (30, 90), (50, 50), (50, 100), (20, 60))]
    vs += [V("MARKET", sl_pips=30, tp_val=tp, partial=30) for tp in (60, 90)]
    for tf in (1, 5, 15):
        for x in (30, 60):
            vs += [V("POI", tf, "poi", tp="rr", tp_val=rr, exp_pips=x) for rr in (1.5, 2, 3)]
            vs += [V("POI", tf, "fix", 50, "pips", 100, exp_pips=x)]
    return vs


def stats(g: pd.DataFrame) -> dict:
    f = g.dropna(subset=["pips"])
    p = f["pips"]
    gw, gl = p[p > 0].sum(), -p[p < 0].sum()
    return {"trades": len(f), "wr%": round(100 * (p > 0).mean(), 1) if len(f) else 0.0,
            "pips": round(p.sum()), "R": round(f["R"].sum(), 1),
            "PF": round(gw / gl, 2) if gl else np.inf,
            "risk": round(f["risk_pips"].median(), 0) if len(f) else 0}


def main() -> None:
    df = load_m1("M1")
    bars = Bars(df)
    arr = {True: (bars.o, bars.h, bars.l, bars.c), False: (-bars.o, -bars.l, -bars.h, -bars.c)}
    pois = {(tf, b): tf_pois(bars, tf, b) for tf in (1, 5, 15) for b in (True, False)}
    signals = load_signals(Store(settings.DB_PATH), df.index[0].to_pydatetime(), df.index[-1].to_pydatetime())
    print(f"Sinyal: {len(signals)}")
    rows = [simulate(sg, v, bars, arr, pois) for v in variants() for sg in signals]
    d = pd.DataFrame(rows)
    d["time"] = pd.to_datetime(d["time"], utc=True)
    d.to_csv(settings.DATA_DIR / "wide_backtest.csv", index=False)
    out = []
    for name, g in d.groupby("variant", sort=False):
        tr, te = stats(g[g.time < SPLIT]), stats(g[g.time >= SPLIT])
        out.append({"variant": name, **{f"tr_{k}": v for k, v in tr.items()},
                    **{f"te_{k}": v for k, v in te.items()}})
    res = pd.DataFrame(out)
    res.to_csv(settings.DATA_DIR / "wide_summary.csv", index=False)
    with pd.option_context("display.width", 230, "display.max_rows", 80):
        print(res.to_string(index=False))


if __name__ == "__main__":
    main()
