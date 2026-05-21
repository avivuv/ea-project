"""
Grid search multi-parameter untuk EA Brain.
Jalankan: python tune.py --pair XAUUSD --csv ../XAUUSD_GMT+0_NO-DST_BAR/XAUUSD_GMT+0_NO-DST_H1.csv --no-trail
"""
from __future__ import annotations

import argparse
import importlib
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import config as cfg
from backtest import load_from_csv, load_from_yfinance, run_backtest

# ── Grid ──────────────────────────────────────────────────────────────────────
SL_GRID         = [2.0, 2.5, 3.0]
TP_GRID         = [4.0, 5.0, 6.0]
ADX_GRID        = [25, 30, 35]
BODY_MULT_GRID  = [0.1, 0.3, 0.5]   # candle body >= atr * X


def _run_combo(df, pair, equity, pip_value, use_trail,
               sl, tp, adx_min, body_mult):
    import technical_signal as ts

    cfg.SL_ATR_MULTIPLIER  = sl
    cfg.TP_ATR_MULTIPLIER  = tp
    cfg.ADX_MIN_LEVEL      = adx_min
    cfg.BODY_MULT          = body_mult   # akan dibaca oleh technical_signal

    importlib.reload(ts)

    import backtest as bt
    importlib.reload(bt)
    bt.compute_signal = ts.compute_signal

    trades, equity_curve, final_equity = bt.run_backtest(
        df.copy(), pair, equity, pip_value,
        use_ai=False, use_trail=use_trail,
    )

    closed  = [t for t in trades if t.close_idx >= 0]
    wins    = [t for t in closed if t.pnl_pct >  0.001]
    losses  = [t for t in closed if t.pnl_pct < -0.001]
    be      = [t for t in closed if abs(t.pnl_pct) <= 0.001]
    n       = len(closed)
    ret     = (final_equity - equity) / equity * 100
    wr      = len(wins) / n * 100 if n else 0
    pf      = (
        abs(sum(t.pnl_pct for t in wins)) / abs(sum(t.pnl_pct for t in losses))
        if losses and sum(t.pnl_pct for t in losses) != 0 else 999.0
    )
    return ret, wr, pf, len(wins), len(be), len(losses), n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair",     default="XAUUSD")
    parser.add_argument("--csv",      default="")
    parser.add_argument("--days",     type=int,   default=59)
    parser.add_argument("--equity",   type=float, default=10000.0)
    parser.add_argument("--pipval",   type=float, default=0.0)
    parser.add_argument("--trail",    action="store_true",
                        help="Aktifkan trailing stop (default: OFF)")
    parser.add_argument("--min-trades", type=int, default=50,
                        help="Filter kombinasi dengan trade < N (hindari overfit)")
    args = parser.parse_args()

    pair = args.pair.upper()
    pip_value = args.pipval
    if pip_value <= 0:
        defaults = {"EURUSD": 10.0, "GBPUSD": 10.0, "USDJPY": 9.0,
                    "XAUUSD": 1.0, "BTCUSD": 1.0}
        pip_value = defaults.get(pair, 10.0)

    df = load_from_csv(args.csv) if args.csv else load_from_yfinance(pair, args.days)

    combos = [
        (sl, tp, adx, body)
        for sl, tp, adx, body in itertools.product(SL_GRID, TP_GRID, ADX_GRID, BODY_MULT_GRID)
        if tp > sl
    ]

    print(f"\nGrid search {pair} | {len(df)} candle | Trail={'ON' if args.trail else 'OFF'}")
    print(f"SL={SL_GRID}  TP={TP_GRID}  ADX={ADX_GRID}  Body={BODY_MULT_GRID}")
    print(f"Total kombinasi: {len(combos)}  (min-trades filter: {args.min_trades})\n")

    header = (f"{'SL':>4} {'TP':>4} {'ADX':>4} {'Body':>5} | "
              f"{'Return':>8} {'WinR':>6} {'W/L':>9} {'PF':>6} {'N':>5}")
    print(header)
    print("-" * len(header))

    results = []
    for i, (sl, tp, adx, body) in enumerate(combos, 1):
        ret, wr, pf, w, be, l, n = _run_combo(
            df, pair, args.equity, pip_value, args.trail,
            sl, tp, adx, body,
        )
        wl = f"{w}/{l}"
        print(f"{sl:>4.1f} {tp:>4.1f} {adx:>4} {body:>5.1f} | "
              f"{ret:>+7.2f}% {wr:>5.1f}% {wl:>9} {pf:>6.2f} {n:>5}")
        if n >= args.min_trades:
            results.append((ret, pf, sl, tp, adx, body, wr, w, be, l, n))

    results.sort(key=lambda x: (x[0], x[1]), reverse=True)

    print("\n" + "=" * 65)
    print(f"  TOP 10 KOMBINASI (return desc, min {args.min_trades} trades)")
    print("=" * 65)
    for ret, pf, sl, tp, adx, body, wr, w, be, l, n in results[:10]:
        print(f"  SL={sl}x TP={tp}x ADX>{adx} Body>{body}x | "
              f"return={ret:+.2f}%  WR={wr:.1f}%  W/L={w}/{l}  PF={pf:.2f}  n={n}")


if __name__ == "__main__":
    main()
