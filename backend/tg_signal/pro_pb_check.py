"""
Backtest filter kedalaman pullback (Cfg.min_pb) pada SMC Top-Down konfigurasi live.

    python -m tg_signal.pro_pb_check

1. Grid min_pb (× ATR14 H1) — disimulasikan ulang di run_side (slot harian yang kosong bisa terisi setup lain).
2. Per kuartal, per arah, deret loss terpanjang.
3. Variasi tetangga untuk kandidat: RR, lookback pullback, slope EMA.
4. Validasi M1 (fill & SL/TP per menit) untuk dasar vs kandidat.
"""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from tg_signal import pro_strategy as ps
from tg_signal.market_data import load_m1
from tg_signal.pro_check import line, m1_validate, run
from tg_signal.pro_live import BIAS_TF, CFG, EMA_SPAN, MIN_SLOPE

GRID = (0.0, 0.4, 0.6, 0.8, 1.0, 1.2, 1.5)
CANDIDATE = 1.0


def streak(t: pd.DataFrame) -> int:
    m = s = 0
    for r in t.R:
        s = s + 1 if r < 0 else 0
        m = max(m, s)
    return m


def main() -> None:
    df = load_m1("M5")
    mk = ps.Market(df, EMA_SPAN, BIAS_TF, MIN_SLOPE)
    print(f"Data M5 {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d} | dasar {CFG.name} slope {MIN_SLOPE}\n")
    res, qs = {}, []
    for pb in GRID:
        t = run(mk, replace(CFG, min_pb=pb))
        res[pb] = t
        al = ps.stats(t)
        print(f"  min_pb {pb:<4} {line(t)} | total R {al['R']:+6.1f} PF {al['PF']:.2f} DD {al['maxDD_R']:4.1f} "
              f"| loss beruntun maks {streak(t)}")
        qs.append(t.groupby(t.time.dt.tz_convert(None).dt.to_period("Q"))["R"].sum().round(1).rename(f"pb {pb}"))
    print("\nR per kuartal:\n" + pd.concat(qs, axis=1).T.to_string())
    for pb in (0.0, CANDIDATE):
        t = res[pb]
        print(f"\nmin_pb {pb} per arah:\n" + t.groupby("dir")["R"].agg(["count", "sum"]).round(1).to_string())

    cand = replace(CFG, min_pb=CANDIDATE)
    print(f"\nTetangga kandidat {cand.name}:")
    for rr in (2.0, 2.5, 4.0):
        print(f"  {'RR ' + str(rr):<20} {line(run(mk, replace(cand, rr=rr)))}")
    orig = ps.PB_LOOKBACK
    for lb in (24, 36, 72, 96):
        ps.PB_LOOKBACK = lb
        print(f"  {'lookback ' + str(lb):<20} {line(run(mk, cand))}")
    ps.PB_LOOKBACK = orig
    for sl in (0.0, 0.2):
        m = ps.Market(df, EMA_SPAN, BIAS_TF, sl)
        print(f"  {'slope ' + str(sl):<20} {line(run(m, cand))}")
    for span in (34, 100):
        m = ps.Market(df, span, BIAS_TF, MIN_SLOPE)
        print(f"  {'EMA ' + str(span):<20} {line(run(m, cand))}")

    for pb in (0.0, CANDIDATE):
        print(f"\n[min_pb {pb}]", end="")
        m1_validate(res[pb])
    res[CANDIDATE].to_csv(ps.settings.DATA_DIR / "pro_pb_trades.csv", index=False)


if __name__ == "__main__":
    main()
