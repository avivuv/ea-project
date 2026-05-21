"""
Backtester v2 — strategy_runner.run_all() (8 strategi, M15 + HTF resample otomatis).

Cara pakai:
  python backtest.py                                          # XAUUSD, auto-cari CSV di ../data/
  python backtest.py --pair XAUUSD --csv ../data/XAUUSD_GMT+0_NO-DST_M15.csv
  python backtest.py --pair XAUUSD --step 4                  # cepat: cek sinyal tiap 1 jam
  python backtest.py --pair XAUUSD --no-trail --equity 5000
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field

import pandas as pd

# Suppress semua log strategi agar backtest tidak lambat karena I/O
logging.disable(logging.CRITICAL)

sys.path.insert(0, os.path.dirname(__file__))

from strategy_runner import run_all
from config import (
    MAX_DRAWDOWN_PCT, MAX_OPEN_TRADES,
    MIN_LOT_SIZE, MAX_LOT_BY_PAIR, MAX_LOT_SIZE,
    PIP_SIZE, MIN_PIP_VALUE, MIN_SL_DISTANCE,
    RISK_PER_TRADE_PCT, FIXED_RISK_USD,
)

WARMUP_CANDLES  = 250    # minimum candle M15 untuk EMA200
H4_BARS         = 250    # jumlah H4 bar yang dikirim ke strategi (250 agar EMA200 H4 bisa dihitung)
D1_BARS         = 60     # jumlah D1 bar
LIMIT_MAX_BARS  = 20     # cancel LIMIT order jika belum terisi setelah N bar M15 (~5 jam)


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class Trade:
    pair:         str
    direction:    str
    order_type:   str
    strategy_id:  str
    open_idx:     int
    open_price:   float
    sl_price:     float
    tp_price:     float
    trail_dist:   float
    lot_size:     float
    initial_sl:   float = 0.0
    close_idx:    int   = -1
    close_price:  float = 0.0
    pnl_pct:      float = 0.0
    close_reason: str   = ""


@dataclass
class PendingOrder:
    pair:        str
    direction:   str
    strategy_id: str
    entry_price: float
    sl_distance: float
    tp_distance: float
    trail_dist:  float
    lot_size:    float
    created_idx: int


@dataclass
class BacktestState:
    equity:      float
    equity_peak: float
    open_trades: list = field(default_factory=list)
    pending:     list = field(default_factory=list)
    ea_paused:   bool = False


# ── CSV Loader ─────────────────────────────────────────────────────────────────

def load_csv(path: str) -> pd.DataFrame:
    with open(path) as f:
        first = f.readline().strip()
    is_mt5 = first.split(",")[0].strip()[:4].isdigit()

    if is_mt5:
        df = pd.read_csv(path, header=None,
                         names=["date", "time_col", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["date"] + " " + df["time_col"], format="%Y.%m.%d %H:%M:%S")
        df = df.drop(columns=["date", "time_col"])
    else:
        df = pd.read_csv(path, parse_dates=["time"])
        df.columns = [c.lower() for c in df.columns]

    df = df.sort_values("time").reset_index(drop=True)
    print(f"  {len(df):,} candle M15 | {df['time'].iloc[0]} s/d {df['time'].iloc[-1]}")
    return df


# ── Resample ───────────────────────────────────────────────────────────────────

def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    d = df.set_index("time").resample(rule).agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum")
    ).dropna()
    return d.reset_index()


def to_ohlcv_list(df: pd.DataFrame, n: int) -> list[dict]:
    tail = df.tail(n)
    return tail.rename(columns={
        "time": "Time", "open": "Open", "high": "High",
        "low": "Low", "close": "Close", "volume": "Volume"
    }).to_dict("records")


# ── Position sizing & P&L ──────────────────────────────────────────────────────

def calc_lot(pair: str, equity: float, sl_distance: float, pip_value: float) -> float:
    pip_size = PIP_SIZE.get(pair, PIP_SIZE["DEFAULT"])
    min_pv   = MIN_PIP_VALUE.get(pair, MIN_PIP_VALUE["DEFAULT"])
    eff_pv   = max(pip_value, min_pv)
    sl_pips  = sl_distance / pip_size
    if sl_pips <= 0 or eff_pv <= 0:
        return 0.0
    risk_usd = FIXED_RISK_USD if FIXED_RISK_USD > 0 else equity * RISK_PER_TRADE_PCT
    raw = risk_usd / (sl_pips * eff_pv)
    pair_max = MAX_LOT_BY_PAIR.get(pair, MAX_LOT_BY_PAIR["DEFAULT"])
    return round(max(MIN_LOT_SIZE, min(raw, min(MAX_LOT_SIZE, pair_max))), 2)


def calc_pnl_usd(pair: str, direction: str, open_p: float, close_p: float,
                 lot: float, pip_value: float) -> float:
    pip_size = PIP_SIZE.get(pair, PIP_SIZE["DEFAULT"])
    eff_pv   = max(pip_value, MIN_PIP_VALUE.get(pair, MIN_PIP_VALUE["DEFAULT"]))
    pips = (close_p - open_p) / pip_size if direction == "BUY" else (open_p - close_p) / pip_size
    return round(pips * eff_pv * lot, 2)


# ── Trailing stop ──────────────────────────────────────────────────────────────

def update_trailing(trade: Trade, high: float, low: float, idx: int) -> None:
    if idx <= trade.open_idx:
        return
    step = trade.trail_dist * 0.1
    if trade.direction == "BUY":
        profit = high - trade.open_price
        if profit >= trade.trail_dist * 2.0:
            new_sl = high - trade.trail_dist
            if new_sl > trade.sl_price + step:
                trade.sl_price = round(new_sl, 5)
        elif profit >= trade.trail_dist and trade.sl_price < trade.open_price:
            trade.sl_price = round(trade.open_price, 5)
    else:
        profit = trade.open_price - low
        if profit >= trade.trail_dist * 2.0:
            new_sl = low + trade.trail_dist
            if trade.sl_price == 0 or new_sl < trade.sl_price - step:
                trade.sl_price = round(new_sl, 5)
        elif profit >= trade.trail_dist and (trade.sl_price == 0 or trade.sl_price > trade.open_price):
            trade.sl_price = round(trade.open_price, 5)


# ── Main backtest loop ─────────────────────────────────────────────────────────

def run_backtest(df_m15: pd.DataFrame, pair: str, initial_equity: float,
                 pip_value: float, use_trail: bool, step: int,
                 no_circuit_breaker: bool = False) -> tuple[list, list, float]:

    print("Resampling ke H4 dan D1...", end=" ", flush=True)
    df_h4 = resample_ohlcv(df_m15, "4h")
    df_d1 = resample_ohlcv(df_m15, "1D")
    print(f"H4={len(df_h4):,} bars | D1={len(df_d1):,} bars")

    state         = BacktestState(equity=initial_equity, equity_peak=initial_equity)
    closed:       list[Trade] = []
    equity_curve: list[float] = []
    records       = df_m15.to_dict("records")
    total         = len(records)
    min_sl        = MIN_SL_DISTANCE.get(pair, 0.0)

    # Index H4 dan D1 agar lookup cepat
    h4_times = df_h4["time"].values
    d1_times = df_d1["time"].values

    t_start = time.time()

    for i in range(WARMUP_CANDLES, total):
        current = records[i]
        high    = current["high"]
        low     = current["low"]
        close   = current["close"]
        t_now   = current["time"]

        # ── 1. Aktivasi LIMIT orders pending ─────────────────────────────────
        open_pairs  = {t.pair for t in state.open_trades}
        new_pending = []
        for pend in state.pending:
            if pend.pair in open_pairs:
                new_pending.append(pend)
                continue
            if i - pend.created_idx > LIMIT_MAX_BARS:
                continue  # expired
            touched = (pend.direction == "BUY"  and low  <= pend.entry_price) or \
                      (pend.direction == "SELL" and high >= pend.entry_price)
            if touched and len(state.open_trades) < MAX_OPEN_TRADES:
                ep = pend.entry_price
                sl_p = round(ep - pend.sl_distance, 5) if pend.direction == "BUY" \
                       else round(ep + pend.sl_distance, 5)
                tp_p = round(ep + pend.tp_distance, 5) if pend.direction == "BUY" \
                       else round(ep - pend.tp_distance, 5)
                trade = Trade(
                    pair=pend.pair, direction=pend.direction, order_type="LIMIT",
                    strategy_id=pend.strategy_id,
                    open_idx=i, open_price=ep, sl_price=sl_p, tp_price=tp_p,
                    trail_dist=pend.trail_dist, lot_size=pend.lot_size, initial_sl=sl_p,
                )
                state.open_trades.append(trade)
                open_pairs.add(pend.pair)
            else:
                new_pending.append(pend)
        state.pending = new_pending

        # ── 2. Cek SL / TP trade open ─────────────────────────────────────────
        still_open = []
        for trade in state.open_trades:
            if use_trail:
                update_trailing(trade, high, low, i)
            hit_sl = (trade.direction == "BUY"  and low  <= trade.sl_price) or \
                     (trade.direction == "SELL" and high >= trade.sl_price)
            hit_tp = (trade.direction == "BUY"  and high >= trade.tp_price) or \
                     (trade.direction == "SELL" and low  <= trade.tp_price)
            if hit_tp or hit_sl:
                exit_p   = trade.tp_price if hit_tp else trade.sl_price
                pnl_usd  = calc_pnl_usd(pair, trade.direction, trade.open_price,
                                        exit_p, trade.lot_size, pip_value)
                trade.close_idx    = i
                trade.close_price  = exit_p
                trade.pnl_pct      = pnl_usd / state.equity
                trade.close_reason = "tp" if hit_tp else "sl"
                state.equity      += pnl_usd
                if state.equity > state.equity_peak:
                    state.equity_peak = state.equity
                closed.append(trade)
            else:
                still_open.append(trade)
        state.open_trades = still_open
        equity_curve.append(round(state.equity, 2))

        # ── 3. Circuit breaker ────────────────────────────────────────────────
        if not no_circuit_breaker:
            if state.equity_peak > 0:
                dd = (state.equity_peak - state.equity) / state.equity_peak
                if dd >= MAX_DRAWDOWN_PCT:
                    state.ea_paused = True
            if state.ea_paused:
                continue

        # ── 4. Skip jika sudah full posisi atau bukan giliran step ────────────
        if len(state.open_trades) >= MAX_OPEN_TRADES:
            continue
        if pair in {t.pair for t in state.open_trades}:
            continue
        if (i - WARMUP_CANDLES) % step != 0:
            continue

        # ── 5. Build HTF slices (binary search sederhana) ─────────────────────
        h4_idx = (h4_times <= t_now).sum()
        d1_idx = (d1_times <= t_now).sum()
        h4_slice = df_h4.iloc[max(0, h4_idx - H4_BARS):h4_idx]
        d1_slice = df_d1.iloc[max(0, d1_idx - D1_BARS):d1_idx]

        m15_ohlcv = to_ohlcv_list(df_m15.iloc[max(0, i - WARMUP_CANDLES + 1):i + 1],
                                   WARMUP_CANDLES)
        h4_ohlcv  = to_ohlcv_list(h4_slice, len(h4_slice)) if len(h4_slice) >= 5 else None
        d1_ohlcv  = to_ohlcv_list(d1_slice, len(d1_slice)) if len(d1_slice) >= 5 else None

        # ── 6. Jalankan semua strategi ────────────────────────────────────────
        try:
            sig = run_all(m15_ohlcv, pair, htf_ohlcv=d1_ohlcv, h4_ohlcv=h4_ohlcv)
        except Exception:
            continue

        if not sig.is_active or sig.sl_distance <= 0:
            continue
        if sig.sl_distance < min_sl:
            continue

        # ── 7. Position sizing ────────────────────────────────────────────────
        lot = calc_lot(pair, state.equity, sig.sl_distance, pip_value)
        if lot <= 0:
            continue

        # ── 8. Buka MARKET atau daftarkan LIMIT ──────────────────────────────
        if sig.order_type == "LIMIT" and sig.entry_price > 0:
            if pair not in {p.pair for p in state.pending}:
                state.pending.append(PendingOrder(
                    pair=pair, direction=sig.direction,
                    strategy_id=sig.strategy_id,
                    entry_price=sig.entry_price,
                    sl_distance=sig.sl_distance, tp_distance=sig.tp_distance,
                    trail_dist=sig.sl_distance, lot_size=lot, created_idx=i,
                ))
        else:
            ep   = close
            sl_p = round(ep - sig.sl_distance, 5) if sig.direction == "BUY" \
                   else round(ep + sig.sl_distance, 5)
            tp_p = round(ep + sig.tp_distance, 5) if sig.direction == "BUY" \
                   else round(ep - sig.tp_distance, 5)
            state.open_trades.append(Trade(
                pair=pair, direction=sig.direction, order_type="MARKET",
                strategy_id=sig.strategy_id,
                open_idx=i, open_price=ep, sl_price=sl_p, tp_price=tp_p,
                trail_dist=sig.sl_distance, lot_size=lot, initial_sl=sl_p,
            ))

        # ── Progress ──────────────────────────────────────────────────────────
        if len(closed) % 10 == 0 and len(closed) > 0:
            elapsed = time.time() - t_start
            pct     = (i - WARMUP_CANDLES) / (total - WARMUP_CANDLES) * 100
            eta     = elapsed / max(pct, 0.01) * (100 - pct)
            print(f"  {pct:5.1f}% | bar={i:,}/{total:,} | trades={len(closed)} "
                  f"| equity=${state.equity:,.2f} | ETA={eta/60:.1f}min", end="\r")

    # Tutup paksa sisa posisi
    last_close = records[-1]["close"]
    for trade in state.open_trades:
        pnl_usd = calc_pnl_usd(pair, trade.direction, trade.open_price,
                                last_close, trade.lot_size, pip_value)
        trade.close_idx    = total - 1
        trade.close_price  = last_close
        trade.pnl_pct      = pnl_usd / state.equity
        trade.close_reason = "end_of_data"
        closed.append(trade)

    paused_note = " [circuit breaker DINONAKTIFKAN]" if no_circuit_breaker else \
                  (" [EA PAUSED oleh max drawdown]" if state.ea_paused else "")
    print(f"\n  Selesai dalam {(time.time()-t_start)/60:.1f} menit | {len(closed)} trades{paused_note}")

    return closed, equity_curve, state.equity


# ── Report ─────────────────────────────────────────────────────────────────────

def print_report(trades: list[Trade], initial_equity: float, final_equity: float,
                 equity_curve: list[float], pair: str):
    if not trades:
        print("\nTidak ada trade yang selesai.")
        return

    wins     = [t for t in trades if t.pnl_pct > 0.001]
    losses   = [t for t in trades if t.pnl_pct < -0.001]
    be       = [t for t in trades if abs(t.pnl_pct) <= 0.001]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    total_r  = (final_equity - initial_equity) / initial_equity * 100

    avg_win  = sum(t.pnl_pct for t in wins)   / len(wins)   * 100 if wins   else 0
    avg_loss = sum(t.pnl_pct for t in losses)  / len(losses) * 100 if losses else 0
    gross_w  = abs(sum(t.pnl_pct for t in wins))
    gross_l  = abs(sum(t.pnl_pct for t in losses))
    pf       = gross_w / gross_l if gross_l > 0 else float("inf")

    peak   = equity_curve[0] if equity_curve else initial_equity
    max_dd = 0.0
    for e in equity_curve:
        if e > peak:
            peak = e
        dd = (peak - e) / peak
        if dd > max_dd:
            max_dd = dd

    by_reason = {}
    for t in trades:
        by_reason[t.close_reason] = by_reason.get(t.close_reason, 0) + 1

    by_type = {}
    for t in trades:
        by_type[t.order_type] = by_type.get(t.order_type, 0) + 1

    print("\n" + "=" * 62)
    print(f"  BACKTEST REPORT  {pair}  (5 tahun, no circuit breaker)")
    print("=" * 62)
    print(f"  Initial equity    : ${initial_equity:,.2f}")
    print(f"  Final equity      : ${final_equity:,.2f}")
    print(f"  Total return      : {total_r:+.2f}%")
    print(f"  Max drawdown      : {max_dd*100:.2f}%")
    print("-" * 62)
    print(f"  Total trades      : {len(trades)}")
    print(f"  Win / BE / Loss   : {len(wins)} / {len(be)} / {len(losses)}")
    print(f"  Win rate          : {win_rate:.1f}%")
    print(f"  Avg win           : {avg_win:+.3f}%")
    print(f"  Avg loss          : {avg_loss:+.3f}%")
    print(f"  Profit factor     : {pf:.2f}")
    print(f"  Order types       : {by_type}")
    print(f"  Close reasons     : {by_reason}")
    print("=" * 62)

    # ── Analisis per strategi ──────────────────────────────────────────────────
    strats = sorted({t.strategy_id for t in trades})
    print(f"\n  {'STRATEGI':<14} {'#':>4} {'WIN':>4} {'WR%':>6} {'PF':>5}  {'AvgW%':>7} {'AvgL%':>7}  Verdict")
    print("  " + "-" * 62)
    strat_rows = []
    for sid in strats:
        st = [t for t in trades if t.strategy_id == sid]
        sw = [t for t in st if t.pnl_pct > 0.001]
        sl = [t for t in st if t.pnl_pct < -0.001]
        wr = len(sw) / len(st) * 100 if st else 0
        gw = abs(sum(t.pnl_pct for t in sw))
        gl = abs(sum(t.pnl_pct for t in sl))
        spf = gw / gl if gl > 0 else float("inf")
        saw = sum(t.pnl_pct for t in sw) / len(sw) * 100 if sw else 0
        sal = sum(t.pnl_pct for t in sl) / len(sl) * 100 if sl else 0
        net = sum(t.pnl_pct for t in st) * 100
        if spf >= 1.5 and wr >= 35:
            verdict = "BAIK"
        elif spf >= 1.0 and wr >= 30:
            verdict = "OK"
        elif len(st) < 3:
            verdict = "data kurang"
        else:
            verdict = "BURUK"
        strat_rows.append((net, sid, len(st), len(sw), wr, spf, saw, sal, verdict))

    strat_rows.sort(reverse=True)
    for net, sid, n, nw, wr, spf, saw, sal, verdict in strat_rows:
        spf_str = f"{spf:.2f}" if spf != float("inf") else " inf"
        print(f"  {sid:<14} {n:>4} {nw:>4} {wr:>5.1f}% {spf_str:>5}  {saw:>+6.2f}% {sal:>+6.2f}%  {verdict}")

    print("\n  Last 10 trades:")
    print(f"  {'#':<4} {'Strategy':<14} {'Dir':<5} {'Open':>10} {'Close':>10} {'PnL%':>8}  Reason")
    print("  " + "-" * 62)
    for idx, t in enumerate(trades[-10:], 1):
        print(f"  {idx:<4} {t.strategy_id:<14} {t.direction:<5} {t.open_price:>10.3f} "
              f"{t.close_price:>10.3f} {t.pnl_pct*100:>+7.3f}%  {t.close_reason}")

    log_path = os.path.join(os.path.dirname(__file__), "logs", f"backtest_{pair}.json")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        json.dump([{
            "pair": t.pair, "direction": t.direction, "order_type": t.order_type,
            "strategy_id": t.strategy_id,
            "open_idx": t.open_idx, "open_price": t.open_price,
            "initial_sl": t.initial_sl, "tp_price": t.tp_price, "final_sl": t.sl_price,
            "close_idx": t.close_idx, "close_price": t.close_price,
            "lot_size": t.lot_size, "pnl_pct": round(t.pnl_pct * 100, 4),
            "close_reason": t.close_reason,
        } for t in trades], f, indent=2)
    print(f"\n  Trade log: {log_path}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="EA Brain Backtester v2")
    parser.add_argument("--pair",     default="XAUUSD")
    parser.add_argument("--csv",      default="", help="Path CSV (MT5 format)")
    parser.add_argument("--tf",       default="M15", choices=["M15", "H1"],
                        help="Timeframe data CSV: M15 atau H1 (default: M15)")
    parser.add_argument("--equity",   type=float, default=10000.0)
    parser.add_argument("--pipval",   type=float, default=0.0, help="0=auto estimate")
    parser.add_argument("--step",     type=int,   default=1,
                        help="Cek sinyal setiap N bar (1=tiap bar, 4=tiap 4 bar). "
                             "Otomatis 1 jika --tf H1.")
    parser.add_argument("--trail",               action="store_true",
                        help="Aktifkan trailing stop (default: OFF)")
    parser.add_argument("--no-circuit-breaker", action="store_true",
                        help="Nonaktifkan circuit breaker max drawdown (lihat performa penuh)")
    args = parser.parse_args()

    pair = args.pair.upper()

    pip_value = args.pipval
    if pip_value <= 0:
        defaults = {"EURUSD": 10.0, "GBPUSD": 10.0, "USDJPY": 9.0,
                    "XAUUSD": 1.0, "US500": 1.0, "USTEC": 1.0, "BTCUSD": 1.0}
        pip_value = defaults.get(pair, 10.0)
        print(f"pip_value estimasi: {pip_value} (override dengan --pipval)")

    tf   = args.tf.upper()
    step = 1 if tf == "H1" else args.step  # H1 data selalu step=1

    csv_path = args.csv
    if not csv_path:
        base = os.path.dirname(__file__)
        candidates = [
            os.path.join(base, "..", "data", f"{pair}_GMT+0_NO-DST_{tf}.csv"),
            os.path.join(base, "..", "data", f"{pair}_{tf}.csv"),
            os.path.join(base, "data", f"{pair}_{tf}.csv"),
        ]
        for c in candidates:
            if os.path.exists(c):
                csv_path = c
                break
        if not csv_path:
            print(f"CSV {tf} tidak ditemukan. Gunakan --csv <path>")
            sys.exit(1)

    print(f"\nBacktest: {pair} | tf={tf} | step={step} | trail={'ON' if args.trail else 'OFF'}")
    print(f"CSV: {csv_path}")
    df = load_csv(csv_path)

    if len(df) < WARMUP_CANDLES + 50:
        print(f"Data terlalu sedikit ({len(df)} candle).")
        sys.exit(1)

    est_bars = (len(df) - WARMUP_CANDLES) // step
    print(f"Estimasi {est_bars:,} iterasi sinyal. Ini mungkin butuh beberapa menit...\n")

    closed, equity_curve, final_equity = run_backtest(
        df, pair, args.equity, pip_value,
        use_trail=args.trail, step=step,
        no_circuit_breaker=args.no_circuit_breaker,
    )
    print_report(closed, args.equity, final_equity, equity_curve, pair)


if __name__ == "__main__":
    main()
