"""
SMC Top-Down mode scalping: struktur yang sama dengan pro_live, timeframe diturunkan.

    python -m tg_signal.pro_scalp_check

Tumpukan timeframe (bias → POI → CHoCH/eksekusi):
  LIVE : H1 → M15 → M5   (konfigurasi live sekarang, pembanding)
  S1   : H1 → M5  → M1
  S2   : M15 → M5 → M1
  S3   : H1 → M15 → M1   (hanya konfirmasi lebih cepat)
Variasi: min_pb (× ATR bias TF), RR, maks trade/hari per arah. Konstanta jumlah bar run_side tetap
(di M1 berarti jendela waktu 5× lebih pendek). Latih < Apr 2026 / uji ≥ Apr 2026.
"""
from __future__ import annotations

import itertools
from dataclasses import replace

import pandas as pd

from tg_signal import pro_strategy as ps
from tg_signal import settings
from tg_signal.market_data import load_m1
from tg_signal.pro_live import CFG, EMA_SPAN, MIN_SLOPE

STACKS = {"LIVE": ("M5", 60, 15, 5), "S1": ("M1", 60, 5, 1), "S2": ("M1", 15, 5, 1), "S3": ("M1", 60, 15, 1)}


def run(mk: ps.Market, cfg: ps.Cfg, max_day: int) -> pd.DataFrame:
    old = ps.MAX_TRADES_DAY
    ps.MAX_TRADES_DAY = max_day
    try:
        t = pd.DataFrame(ps.run_side(mk, cfg, True) + ps.run_side(mk, cfg, False))
    finally:
        ps.MAX_TRADES_DAY = old
    return t.sort_values("time").reset_index(drop=True) if not t.empty else t


def main() -> None:
    m1 = load_m1("M1")
    m1 = m1[m1.index >= "2025-06-16"]
    m5 = load_m1("M5")
    m5 = m5[m5.index >= "2025-06-16"]
    rows, keep = [], {}
    for name, (tf, bias_tf, poi_tf, bar_min) in STACKS.items():
        mk = ps.Market(m1 if tf == "M1" else m5, EMA_SPAN, bias_tf, MIN_SLOPE, poi_tf=poi_tf, bar_min=bar_min)
        grid = [(1.0, 3.0, 3)] if name == "LIVE" else itertools.product((0.0, 0.5, 1.0), (2.0, 3.0), (3, 6))
        for pb, rr, md in grid:
            cfg = replace(CFG, min_pb=pb, rr=rr)
            t = run(mk, cfg, md)
            if t.empty:
                continue
            key = f"{name}_pb{pb:g}_RR{rr:g}_max{md}"
            keep[key] = t
            tr, te = ps.stats(t[t.time < ps.SPLIT]), ps.stats(t[t.time >= ps.SPLIT])
            al = ps.stats(t)
            rows.append({"var": key, "risk_pips_med": t.risk_pips.median(),
                         **{f"tr_{k}": v for k, v in tr.items()}, **{f"te_{k}": v for k, v in te.items()},
                         "all_R": al["R"], "all_PF": al["PF"], "all_DD": al["maxDD_R"]})
            print(f"  {key:<24} risk {t.risk_pips.median():5.1f}p | latih {tr['trades']:4d} PF {tr['PF']:.2f} "
                  f"R {tr['R']:+6.1f} DD {tr['maxDD_R']:4.1f} | uji {te['trades']:4d} PF {te['PF']:.2f} "
                  f"R {te['R']:+6.1f} DD {te['maxDD_R']:4.1f} | {al['per_mgg']}/mgg", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(settings.DATA_DIR / "pro_scalp_grid.csv", index=False)
    pd.concat([t.assign(var=k) for k, t in keep.items()]).to_csv(settings.DATA_DIR / "pro_scalp_trades.csv",
                                                                 index=False)
    ok = res[(res.tr_PF > 1.2) & (res.te_PF > 1.2) & (res.tr_trades >= 80) & (res.te_trades >= 60)]
    with pd.option_context("display.width", 250):
        print(f"\nPF > 1.2 di latih & uji: {len(ok)} dari {len(res)}")
        print(ok.sort_values("all_R", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
