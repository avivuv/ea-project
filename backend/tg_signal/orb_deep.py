"""
Uji mendalam kandidat ORB instrumen lain (hasil orb_pairs.py). Hanya backtest.

    python -m tg_signal.orb_deep

Per kandidat: tetangga parameter, per kuartal & arah, spread 1.5× / 2×, kontrol (entry di akhir OR
searah bias / acak tanpa breakout), lalu portofolio bersama SMC Top-Down & ORB XAUUSD (R harian).
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from tg_signal import orb
from tg_signal import pro_strategy as ps
from tg_signal.market_data import load_m1
from tg_signal.pro_check import run as pro_run
from tg_signal.pro_live import BIAS_TF, CFG as PRO_CFG, EMA_SPAN, MIN_SLOPE
from tg_signal.pro_pairs import load
from tg_signal.session_sweep import Data, simulate

CANDS = {
    "ETHUSD": orb.Cfg("ny", 30, "bar", "market", "opp", "2", "none", "none"),
    "BTCUSD": orb.Cfg("ny", 30, "bar", "market", "opp", "2", "with", "none"),
    "USDJPY": orb.Cfg("london", 30, "bar", "market", "opp", "3", "with", "none"),
}


def setup(df: pd.DataFrame, mult: float = 1.0) -> Data:
    spr = float(df.spread.median())
    orb.SL_BUF, orb.RISK_MIN = 0.6 * spr, 6 * spr
    if mult != 1.0:
        df = df.copy()
        df["spread"] = df["spread"] * mult
    return Data(df)


def line(t: pd.DataFrame) -> str:
    a, b = orb.stats(t[t.time < orb.SPLIT]), orb.stats(t[t.time >= orb.SPLIT])
    return (f"latih n{a['n']:4d} PF {a['PF']:.2f} avgR {a['avgR']:+.2f} DD {a['DD']:5.1f} | "
            f"uji n{b['n']:4d} PF {b['PF']:.2f} avgR {b['avgR']:+.2f} DD {b['DD']:5.1f}")


def control(d: Data, cfg: orb.Cfg, opens: list[int], use_bias: bool) -> pd.DataFrame:
    """Entry di open bar setelah OR selesai, arah = bias H1 (atau acak), SL/TP sama seperti ORB."""
    rng = np.random.default_rng(0)
    out = []
    for i0 in opens:
        i_or = int(np.searchsorted(d.t, d.t[i0] + np.timedelta64(cfg.or_min, "m")))
        i_x = int(np.searchsorted(d.t, d.t[i0] + np.timedelta64(orb.HOLD_MIN, "m")))
        if i_x >= d.n or i_or >= i_x:
            continue
        hi, lo = d.arr[True][1][i0:i_or].max(), d.arr[True][2][i0:i_or].min()
        if use_bias:
            dirs = [b for b in (True, False) if d.bias[b][i_or - 1]]
        else:
            dirs = [bool(rng.integers(2))]
        for b in dirs:
            O = d.arr[b][0]
            ent = O[i_or] + (d.spr[i_or] if b else 0.0)
            sl = (lo if b else -hi) - orb.SL_BUF
            risk = ent - sl
            if risk < orb.RISK_MIN:
                continue
            tp = np.inf if cfg.tp == "eod" else ent + float(cfg.tp) * risk
            r = simulate(d, b, i_or, i_x, ent, None, sl, tp, 0)
            if r:
                out.append({"time": pd.Timestamp(d.t[i_or], tz="UTC"), "R": r[3]})
    return pd.DataFrame(out)


def deep(sym: str, base: orb.Cfg) -> pd.DataFrame:
    df = load(sym, False)
    df = df[df.index >= "2025-06-16"]
    d = setup(df)
    op = orb.open_index(d, base.session)
    t = orb.run(d, base, op)
    print(f"\n{'=' * 100}\n{sym} — {base.name}\n  DASAR            {line(t)}")
    print("  per kuartal R:", t.groupby(t.time.dt.tz_convert(None).dt.to_period("Q")).R.sum().round(1).to_dict())
    print("  per arah     :", t.groupby("dir").R.agg(["count", "sum"]).round(1).to_dict("index"),
          "| outcome:", t.outcome.value_counts().to_dict())
    print("  tetangga:")
    vars_ = [("or_min", v) for v in (15, 20, 45, 60) if v != base.or_min]
    vars_ += [("sl", "mid" if base.sl == "opp" else "opp"), ("entry", "retest"),
              ("bias", "with" if base.bias == "none" else "none")]
    vars_ += [("tp", v) for v in ("1.5", "2", "3", "eod") if v != base.tp]
    for k, v in vars_:
        print(f"    {k}={v:<10} {line(orb.run(d, replace(base, **{k: v}), op))}")
    for attr, vals in (("HOLD_MIN", (180, 240, 480)), ("BREAK_WAIT", (60, 180))):
        old = getattr(orb, attr)
        for v in vals:
            setattr(orb, attr, v)
            print(f"    {attr}={v:<6} {line(orb.run(d, base, op))}")
        setattr(orb, attr, old)
    for m in (1.5, 2.0):
        dm = setup(df, m)
        print(f"    spread ×{m:<6} {line(orb.run(dm, base, orb.open_index(dm, base.session)))}")
    setup(df)
    print(f"  KONTROL bias tanpa breakout   {line(control(d, base, op, True))}")
    print(f"  KONTROL arah acak             {line(control(d, base, op, False))}")
    return t.assign(strat=f"ORB_{sym}")


def main() -> None:
    trades = [deep(s, c) for s, c in CANDS.items()]
    orb.SL_BUF, orb.RISK_MIN = 0.1, 1.0
    m1 = load_m1("M1")
    dx = Data(m1[m1.index >= "2025-06-16"])
    xau = orb.run(dx, orb.LIVE_CFG, orb.open_index(dx, "ny")).assign(strat="ORB_XAUUSD")
    m5 = load_m1("M5")
    smc = pro_run(ps.Market(m5[m5.index >= "2025-06-16"], EMA_SPAN, BIAS_TF, MIN_SLOPE), PRO_CFG).assign(strat="SMC")
    allt = pd.concat([x[["time", "R", "strat"]] for x in [smc, xau] + trades])
    end = min(g.time.max() for _, g in allt.groupby("strat"))
    allt = allt[allt.time <= end]
    day = allt.assign(day=allt.time.dt.tz_convert("Asia/Jakarta").dt.date).pivot_table(
        index="day", columns="strat", values="R", aggfunc="sum").fillna(0)
    print(f"\n{'=' * 100}\nKorelasi R harian:\n{day.corr().round(2).to_string()}")
    mo = allt.assign(m=allt.time.dt.tz_convert(None).dt.to_period("M")).pivot_table(
        index="m", columns="strat", values="R", aggfunc="sum").fillna(0)
    print(f"\nKorelasi R bulanan:\n{mo.corr().round(2).to_string()}")

    def port(names):
        r = allt[allt.strat.isin(names)].sort_values("time").R
        eq = r.cumsum()
        dd = float((eq.cummax() - eq).max())
        mm = mo[names].sum(axis=1)
        return f"n {len(r):4d} R {r.sum():+7.1f} DD {dd:5.1f} R/DD {r.sum() / dd:5.1f} bulan minus {(mm < 0).sum()}/{len(mm)}"

    base = ["SMC", "ORB_XAUUSD"]
    print("\nPortofolio (risiko 1R per trade tiap strategi):")
    print(f"  {'SMC + ORB XAU (sekarang)':<34} {port(base)}")
    for s in CANDS:
        print(f"  {'+ ORB ' + s:<34} {port(base + [f'ORB_{s}'])}")
    print(f"  {'+ semua kandidat':<34} {port(base + [f'ORB_{s}' for s in CANDS])}")


if __name__ == "__main__":
    main()
