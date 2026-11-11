"""
Uji multi-tahun ORB di bar M15 Exness (Sep 2022 – Nov 2026), aturan TIDAK disetel ulang.

    python -m intraday.multiyear

1. Kalibrasi: versi M15 vs versi M5 di periode yang sama (Jun 2025 – Nov 2026).
2. Hasil per tahun untuk semua variasi ORB (London/NY, range 15/30, SL seberang/tengah, TP 1,5R/2R/akhir sesi).
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from intraday.backtest import S2, Bars, s2_orders, simulate, stats
from tg_signal.market_data import load_m1


def per_year(tr: pd.DataFrame) -> dict:
    tr = tr.dropna(subset=["r"])
    return {str(y): round(g["r"].sum(), 1) for y, g in tr.groupby(tr["time"].dt.year)}


def main() -> None:
    pd.set_option("display.width", 250)
    m15, m5 = load_m1("M15"), load_m1("M5")
    b15, b5 = Bars(m15), Bars(m5)

    print("== Kalibrasi Jun 2025 – Nov 2026: bar M15 vs bar M5 ==")
    start = pd.Timestamp("2025-06-17", tz="UTC")
    for p in (S2("london", 15, "opp", "eod"), S2("london", 15, "mid", "eod"), S2("london", 30, "opp", "eod")):
        r15 = simulate([o for o in s2_orders(m15, p, 15) if o.active >= start], b15)
        r5 = simulate([o for o in s2_orders(m5, p, 5) if o.active >= start], b5)
        print(f"  {p.name:<30} M15: {stats(r15, 17)} \n  {'':<30} M5 : {stats(r5, 17)}")

    print("\n== Semua variasi ORB di M15, Sep 2022 – Nov 2026: total R per tahun ==")
    rows = []
    months = (m15.index[-1] - m15.index[0]).days / 30.4
    for s, rng, sl, tp in itertools.product(("london", "ny"), (15, 30), ("opp", "mid"), ("1.5R", "2R", "eod")):
        p = S2(s, rng, sl, tp)
        tr = simulate(s2_orders(m15, p, 15), b15)
        st = stats(tr, months)
        py = per_year(tr)
        rows.append({"variasi": p.name, **{k: st[k] for k in ("trades", "WR%", "avgR", "totR", "PF", "DD_R")},
                     **py, "tahun_positif": f"{sum(v > 0 for v in py.values())}/{len(py)}"})
    res = pd.DataFrame(rows).sort_values("avgR", ascending=False)
    print(res.to_string(index=False))
    res.to_csv("tg_signal/data/intraday_multiyear.csv", index=False)


if __name__ == "__main__":
    main()
