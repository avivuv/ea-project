"""
Backtest BPR (Balanced Price Range) — XAUUSD M15 only (tanpa HTF filter).

Mode default: satu run dengan parameter yang dipilih.
Mode sweep  : bandingkan 4 kombinasi parameter secara berurutan.

Cara pakai:
  python backtest_bpr.py                            # run default (prox=2.0 age=80)
  python backtest_bpr.py --sweep                    # bandingkan 4 kombis, step=4
  python backtest_bpr.py --prox 2.5 --age 100       # custom params
  python backtest_bpr.py --no-circuit-breaker
  python backtest_bpr.py --trail --step 1
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
import ta

logging.disable(logging.CRITICAL)

sys.path.insert(0, os.path.dirname(__file__))

import strategies.strategy_bpr as _bpr_mod   # patching module globals untuk sweep
from strategies.strategy_bpr import StrategyBPR
from config import (
    MAX_DRAWDOWN_PCT,
    MIN_LOT_SIZE, MAX_LOT_BY_PAIR, MAX_LOT_SIZE,
    PIP_SIZE, MIN_PIP_VALUE, MIN_SL_DISTANCE,
    RISK_PER_TRADE_PCT, FIXED_RISK_USD,
)

PAIR          = "XAUUSD"
WARMUP        = 250
LIMIT_MAX_BARS = 20

# ── Kombinasi parameter untuk mode sweep ──────────────────────────────────────
SWEEP_CONFIGS = [
    dict(label="ZG5-T48 ", prox=2.5, age=100, gap=0.15, disp=0.3, rr=3.0, temporal=48,  zone_gap=5.0),
    dict(label="ZG8-T48 ", prox=2.5, age=100, gap=0.15, disp=0.3, rr=3.0, temporal=48,  zone_gap=8.0),
    dict(label="ZG8-T96 ", prox=2.5, age=100, gap=0.15, disp=0.3, rr=3.0, temporal=96,  zone_gap=8.0),
    dict(label="ZG10-T96", prox=2.5, age=100, gap=0.10, disp=0.2, rr=3.0, temporal=96,  zone_gap=10.0),
]


@dataclass
class Trade:
    direction:    str
    order_type:   str
    mode_tag:     str
    open_idx:     int
    open_price:   float
    sl_price:     float
    tp_price:     float
    trail_dist:   float
    lot_size:     float
    confidence:   float
    close_idx:    int   = -1
    close_price:  float = 0.0
    pnl_pct:      float = 0.0
    close_reason: str   = ""


@dataclass
class PendingOrder:
    direction:   str
    entry_price: float
    sl_distance: float
    tp_distance: float
    trail_dist:  float
    lot_size:    float
    confidence:  float
    created_idx: int


@dataclass
class BtState:
    equity:      float
    equity_peak: float
    open_trades: list = field(default_factory=list)
    pending:     list = field(default_factory=list)
    ea_paused:   bool = False


# ── CSV & helpers ──────────────────────────────────────────────────────────────

def load_csv(path: str) -> pd.DataFrame:
    with open(path) as f:
        first = f.readline().strip()
    is_mt5 = first.split(",")[0].strip()[:4].isdigit()
    if is_mt5:
        df = pd.read_csv(path, header=None,
                         names=["date","time_col","open","high","low","close","volume"])
        df["time"] = pd.to_datetime(df["date"] + " " + df["time_col"],
                                    format="%Y.%m.%d %H:%M:%S")
        df = df.drop(columns=["date", "time_col"])
    else:
        df = pd.read_csv(path, parse_dates=["time"])
        df.columns = [c.lower() for c in df.columns]
    df = df.sort_values("time").reset_index(drop=True)
    return df


def to_list(df: pd.DataFrame) -> list[dict]:
    return df.rename(columns={
        "time":"Time","open":"Open","high":"High",
        "low":"Low","close":"Close","volume":"Volume"
    }).to_dict("records")


def calc_lot(equity: float, sl_distance: float, pip_value: float) -> float:
    pip_size = PIP_SIZE.get(PAIR, PIP_SIZE["DEFAULT"])
    eff_pv   = max(pip_value, MIN_PIP_VALUE.get(PAIR, MIN_PIP_VALUE["DEFAULT"]))
    sl_pips  = sl_distance / pip_size
    if sl_pips <= 0 or eff_pv <= 0:
        return 0.0
    risk_usd = FIXED_RISK_USD if FIXED_RISK_USD > 0 else equity * RISK_PER_TRADE_PCT
    pair_max = MAX_LOT_BY_PAIR.get(PAIR, MAX_LOT_BY_PAIR["DEFAULT"])
    return round(max(MIN_LOT_SIZE, min(risk_usd / (sl_pips * eff_pv),
                                       min(MAX_LOT_SIZE, pair_max))), 2)


def calc_pnl(direction: str, open_p: float, close_p: float,
             lot: float, pip_value: float) -> float:
    pip_size = PIP_SIZE.get(PAIR, PIP_SIZE["DEFAULT"])
    eff_pv   = max(pip_value, MIN_PIP_VALUE.get(PAIR, MIN_PIP_VALUE["DEFAULT"]))
    pips = (close_p - open_p) / pip_size if direction == "BUY" \
           else (open_p - close_p) / pip_size
    return round(pips * eff_pv * lot, 2)


def update_breakeven(trade: Trade, high: float, low: float, idx: int) -> None:
    """Geser SL ke entry setelah profit 1R (break-even stop)."""
    if idx <= trade.open_idx:
        return
    if trade.direction == "BUY":
        sl_dist = trade.open_price - trade.sl_price
        if sl_dist > 0 and high >= trade.open_price + sl_dist:
            if trade.sl_price < trade.open_price:
                trade.sl_price = round(trade.open_price, 5)
    else:
        sl_dist = trade.sl_price - trade.open_price
        if sl_dist > 0 and low <= trade.open_price - sl_dist:
            if trade.sl_price > trade.open_price:
                trade.sl_price = round(trade.open_price, 5)


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


# ── Patch module globals (untuk sweep tanpa restart proses) ───────────────────

def patch_params(prox: float, age: int, gap: float, disp: float, rr: float,
                 temporal: int, zone_gap: float,
                 rsi_filter: bool = False,
                 rsi_buy_max: float = 55.0, rsi_sell_min: float = 45.0,
                 adx_filter: bool = False,
                 adx_period: int = 14, adx_min: float = 20.0) -> None:
    _bpr_mod.BPR_PROXIMITY_ATR           = prox
    _bpr_mod.BPR_MAX_AGE_BARS            = age
    _bpr_mod.BPR_MIN_GAP_ATR             = gap
    _bpr_mod.BPR_DISPLACEMENT_RATIO      = disp
    _bpr_mod.BPR_RR                      = rr
    _bpr_mod.BPR_MAX_TEMPORAL_GAP        = temporal
    _bpr_mod.BPR_MAX_ZONE_GAP_ATR_PAIRS  = {"XAUUSD": zone_gap}
    _bpr_mod.BPR_RSI_FILTER              = rsi_filter
    _bpr_mod.BPR_RSI_BUY_MAX             = rsi_buy_max
    _bpr_mod.BPR_RSI_SELL_MIN            = rsi_sell_min
    _bpr_mod.BPR_ADX_FILTER              = adx_filter
    _bpr_mod.BPR_ADX_PERIOD              = adx_period
    _bpr_mod.BPR_ADX_MIN                 = adx_min
    _bpr_mod.BPR_HTF_TREND_FILTER        = False   # M15 only — matikan HTF filter


# ── Backtest core ──────────────────────────────────────────────────────────────

def _build_ema_trend(records: list[dict], ema_period: int = 50) -> list[str | None]:
    """Hitung EMA trend untuk setiap bar. BUY=close>EMA, SELL=close<EMA, None=warmup."""
    closes = pd.Series([r["close"] for r in records])
    ema    = ta.trend.ema_indicator(closes, window=ema_period)
    result: list[str | None] = []
    for i, (c, e) in enumerate(zip(closes, ema)):
        if pd.isna(e):
            result.append(None)
        else:
            result.append("BUY" if c > e else "SELL")
    return result


def run_backtest(
    records: list[dict],
    total: int,
    initial_equity: float,
    pip_value: float,
    use_trail: bool,
    step: int,
    no_cb: bool,
    label: str = "",
    ema_trend_filter: bool = False,
    ema_period: int = 50,
    session_filter: bool = False,
    use_be: bool = False,
) -> tuple[list[Trade], list[float], float]:

    bpr       = StrategyBPR()   # fresh instance — baca globals yang sudah di-patch
    ema_trend = _build_ema_trend(records, ema_period) if ema_trend_filter else None
    state     = BtState(equity=initial_equity, equity_peak=initial_equity)
    closed:   list[Trade] = []
    eq_curve: list[float] = []
    min_sl    = MIN_SL_DISTANCE.get(PAIR, 0.0)
    t_start   = time.time()
    prefix    = f"[{label}] " if label else ""

    for i in range(WARMUP, total):
        current = records[i]
        high    = current["high"]
        low     = current["low"]
        close   = current["close"]

        # 1. Aktivasi LIMIT
        new_pending = []
        for pend in state.pending:
            if state.open_trades:
                new_pending.append(pend)
                continue
            if i - pend.created_idx > LIMIT_MAX_BARS:
                continue
            touched = (pend.direction == "BUY"  and low  <= pend.entry_price) or \
                      (pend.direction == "SELL" and high >= pend.entry_price)
            if touched:
                ep   = pend.entry_price
                sl_p = round(ep - pend.sl_distance, 5) if pend.direction == "BUY" \
                       else round(ep + pend.sl_distance, 5)
                tp_p = round(ep + pend.tp_distance, 5) if pend.direction == "BUY" \
                       else round(ep - pend.tp_distance, 5)
                state.open_trades.append(Trade(
                    direction=pend.direction, order_type="LIMIT", mode_tag="limit",
                    open_idx=i, open_price=ep, sl_price=sl_p, tp_price=tp_p,
                    trail_dist=pend.trail_dist, lot_size=pend.lot_size,
                    confidence=pend.confidence,
                ))
            else:
                new_pending.append(pend)
        state.pending = new_pending

        # 2. Cek SL / TP
        still_open = []
        for trade in state.open_trades:
            if use_trail:
                update_trailing(trade, high, low, i)
            elif use_be:
                update_breakeven(trade, high, low, i)
            hit_sl = (trade.direction == "BUY"  and low  <= trade.sl_price) or \
                     (trade.direction == "SELL" and high >= trade.sl_price)
            hit_tp = (trade.direction == "BUY"  and high >= trade.tp_price) or \
                     (trade.direction == "SELL" and low  <= trade.tp_price)
            if hit_tp or hit_sl:
                exit_p            = trade.tp_price if hit_tp else trade.sl_price
                pnl_usd           = calc_pnl(trade.direction, trade.open_price,
                                             exit_p, trade.lot_size, pip_value)
                trade.close_idx   = i
                trade.close_price = exit_p
                trade.pnl_pct     = pnl_usd / state.equity
                trade.close_reason = "tp" if hit_tp else "sl"
                state.equity     += pnl_usd
                if state.equity > state.equity_peak:
                    state.equity_peak = state.equity
                closed.append(trade)
            else:
                still_open.append(trade)
        state.open_trades = still_open
        eq_curve.append(round(state.equity, 2))

        # 3. Circuit breaker
        if not no_cb:
            if state.equity_peak > 0:
                dd = (state.equity_peak - state.equity) / state.equity_peak
                if dd >= MAX_DRAWDOWN_PCT:
                    state.ea_paused = True
            if state.ea_paused:
                continue

        if state.open_trades or state.pending:
            continue
        if (i - WARMUP) % step != 0:
            continue

        # Session filter: London 08-12 GMT, NY 13-18 GMT
        if session_filter:
            h = current["time"].hour
            if not (8 <= h < 12 or 13 <= h < 18):
                continue

        # 4. Buat slice M15 saja — tidak ada H4 (htf_trend=None → BUY+SELL keduanya aktif)
        m15_slice = records[max(0, i - WARMUP + 1): i + 1]

        try:
            sig = bpr.compute(m15_slice, PAIR)   # tanpa h4_ohlcv
        except Exception:
            continue

        if not sig.is_active or sig.sl_distance <= 0:
            continue

        # EMA trend filter: skip sinyal counter-trend
        if ema_trend is not None:
            trend = ema_trend[i]
            if trend is not None and sig.direction != trend:
                continue
        if sig.sl_distance < min_sl:
            continue

        lot = calc_lot(state.equity, sig.sl_distance, pip_value)
        if lot <= 0:
            continue

        mode_tag = "bounce" if "bounce" in sig.reason else "limit"

        if sig.order_type == "LIMIT" and sig.entry_price > 0:
            state.pending.append(PendingOrder(
                direction=sig.direction, entry_price=sig.entry_price,
                sl_distance=sig.sl_distance, tp_distance=sig.tp_distance,
                trail_dist=sig.sl_distance, lot_size=lot, confidence=sig.confidence,
                created_idx=i,
            ))
        else:
            ep   = close
            sl_p = round(ep - sig.sl_distance, 5) if sig.direction == "BUY" \
                   else round(ep + sig.sl_distance, 5)
            tp_p = round(ep + sig.tp_distance, 5) if sig.direction == "BUY" \
                   else round(ep - sig.tp_distance, 5)
            state.open_trades.append(Trade(
                direction=sig.direction, order_type="MARKET", mode_tag=mode_tag,
                open_idx=i, open_price=ep, sl_price=sl_p, tp_price=tp_p,
                trail_dist=sig.sl_distance, lot_size=lot, confidence=sig.confidence,
            ))

        if len(closed) % 5 == 0 and len(closed) > 0:
            elapsed = time.time() - t_start
            pct     = (i - WARMUP) / (total - WARMUP) * 100
            eta     = elapsed / max(pct, 0.01) * (100 - pct)
            print(f"  {prefix}{pct:5.1f}% | trades={len(closed)} "
                  f"| eq=${state.equity:,.0f} | ETA={eta/60:.1f}m", end="\r")

    # Tutup sisa posisi
    last_close = records[-1]["close"]
    for trade in state.open_trades:
        pnl_usd = calc_pnl(trade.direction, trade.open_price,
                            last_close, trade.lot_size, pip_value)
        trade.close_idx    = total - 1
        trade.close_price  = last_close
        trade.pnl_pct      = pnl_usd / state.equity
        trade.close_reason = "end_of_data"
        closed.append(trade)

    elapsed = time.time() - t_start
    paused  = " [CB paused]" if state.ea_paused else ""
    print(f"  {prefix}Selesai {elapsed/60:.1f} menit | {len(closed)} trades{paused}      ")
    return closed, eq_curve, state.equity


# ── Report ─────────────────────────────────────────────────────────────────────

def _stats(trades: list[Trade]) -> dict:
    if not trades:
        return dict(n=0, wins=0, wr=0, pf=0, ret=0, max_dd=0)
    wins   = [t for t in trades if t.pnl_pct > 0.001]
    losses = [t for t in trades if t.pnl_pct < -0.001]
    gw     = abs(sum(t.pnl_pct for t in wins))
    gl     = abs(sum(t.pnl_pct for t in losses))
    return dict(
        n=len(trades), wins=len(wins),
        wr=len(wins)/len(trades)*100,
        pf=gw/gl if gl > 0 else float("inf"),
        ret=sum(t.pnl_pct for t in trades)*100,
    )


def print_sweep_summary(results: list[tuple[dict, list[Trade]]]) -> None:
    print("\n" + "=" * 72)
    print("  SWEEP SUMMARY — BPR XAUUSD M15 (tanpa HTF filter)")
    print("=" * 72)
    print(f"  {'Label':<10} {'prox':>5} {'age':>4} {'gap':>5} {'disp':>5} {'RR':>4} {'ZG':>5} "
          f"{'#':>4} {'WR%':>6} {'PF':>5} {'Ret%':>7}  Verdict")
    print("  " + "-" * 78)
    for cfg, trades in results:
        s = _stats(trades)
        pf_s = f"{s['pf']:.2f}" if s['pf'] != float("inf") else " inf"
        if s['n'] < 5:
            verdict = "data kurang"
        elif s['pf'] >= 1.5 and s['wr'] >= 38:
            verdict = "BAIK **"
        elif s['pf'] >= 1.0 and s['wr'] >= 30:
            verdict = "OK"
        else:
            verdict = "buruk"
        print(f"  {cfg['label']:<10} {cfg['prox']:>5.1f} {cfg['age']:>4} "
              f"{cfg['gap']:>5.2f} {cfg['disp']:>5.1f} {cfg['rr']:>4.1f} {cfg['zone_gap']:>5.1f} "
              f"{s['n']:>4} {s['wr']:>5.1f}% {pf_s:>5} {s['ret']:>+6.2f}%  {verdict}")
    print("=" * 72)


def print_report(trades: list[Trade], initial_equity: float, final_equity: float,
                 eq_curve: list[float], cfg: dict, save_json: bool = True) -> None:
    if not trades:
        print("\nTidak ada trade.")
        return

    wins     = [t for t in trades if t.pnl_pct > 0.001]
    losses   = [t for t in trades if t.pnl_pct < -0.001]
    be       = [t for t in trades if abs(t.pnl_pct) <= 0.001]
    wr       = len(wins) / len(trades) * 100
    total_r  = (final_equity - initial_equity) / initial_equity * 100
    avg_win  = sum(t.pnl_pct for t in wins)   / len(wins)   * 100 if wins   else 0
    avg_loss = sum(t.pnl_pct for t in losses)  / len(losses) * 100 if losses else 0
    gw       = abs(sum(t.pnl_pct for t in wins))
    gl       = abs(sum(t.pnl_pct for t in losses))
    pf       = gw / gl if gl > 0 else float("inf")

    peak   = eq_curve[0] if eq_curve else initial_equity
    max_dd = 0.0
    for e in eq_curve:
        if e > peak:
            peak = e
        dd = (peak - e) / peak
        if dd > max_dd:
            max_dd = dd

    bounce_t = [t for t in trades if t.mode_tag == "bounce"]
    limit_t  = [t for t in trades if t.mode_tag == "limit"]
    buy_t    = [t for t in trades if t.direction == "BUY"]
    sell_t   = [t for t in trades if t.direction == "SELL"]

    def ms(lst):
        if not lst: return "0"
        w = [t for t in lst if t.pnl_pct > 0.001]
        l = [t for t in lst if t.pnl_pct < -0.001]
        gw_ = abs(sum(t.pnl_pct for t in w))
        gl_ = abs(sum(t.pnl_pct for t in l))
        pf_ = gw_/gl_ if gl_ > 0 else float("inf")
        return f"{len(lst)} | WR {len(w)/len(lst)*100:.0f}% | PF {pf_ if pf_!=float('inf') else '∞':.2f}"

    print("\n" + "=" * 65)
    print(f"  BACKTEST BPR — {PAIR} M15  [{cfg['label'].strip()}]")
    print(f"  prox={cfg['prox']} age={cfg['age']} gap={cfg['gap']} "
          f"disp={cfg['disp']} RR={cfg['rr']} | HTF filter: OFF")
    print("=" * 65)
    print(f"  Initial equity  : ${initial_equity:,.2f}")
    print(f"  Final equity    : ${final_equity:,.2f}")
    print(f"  Total return    : {total_r:+.2f}%")
    print(f"  Max drawdown    : {max_dd*100:.2f}%")
    print("-" * 65)
    print(f"  Total trades    : {len(trades)}")
    print(f"  Win/BE/Loss     : {len(wins)}/{len(be)}/{len(losses)}")
    print(f"  Win rate        : {wr:.1f}%")
    print(f"  Avg win         : {avg_win:+.3f}%")
    print(f"  Avg loss        : {avg_loss:+.3f}%")
    print(f"  Profit factor   : {pf:.2f}")
    print("-" * 65)
    print(f"  Bounce (MARKET) : {ms(bounce_t)}")
    print(f"  Limit (LIMIT)   : {ms(limit_t)}")
    print(f"  BUY             : {ms(buy_t)}")
    print(f"  SELL            : {ms(sell_t)}")
    print("=" * 65)

    # Confidence buckets
    buckets = [(0.35,0.50),(0.50,0.65),(0.65,0.80),(0.80,1.01)]
    print(f"\n  {'Conf range':>12} {'#':>4} {'WIN':>4} {'WR%':>6} {'PF':>5}")
    print("  " + "-" * 38)
    for lo, hi in buckets:
        bt = [t for t in trades if lo <= t.confidence < hi]
        if not bt:
            continue
        bw = [t for t in bt if t.pnl_pct > 0.001]
        bl = [t for t in bt if t.pnl_pct < -0.001]
        bgw = abs(sum(t.pnl_pct for t in bw))
        bgl = abs(sum(t.pnl_pct for t in bl))
        bpf = bgw/bgl if bgl > 0 else float("inf")
        bpf_s = f"{bpf:.2f}" if bpf != float("inf") else " inf"
        print(f"  [{lo:.2f}-{hi:.2f})   {len(bt):>4} {len(bw):>4} "
              f"{len(bw)/len(bt)*100:>5.1f}% {bpf_s:>5}")

    print(f"\n  {'#':<4} {'Dir':<5} {'Mode':<8} {'Conf':>5} "
          f"{'Open':>8} {'Close':>8} {'PnL%':>8}  Reason")
    print("  " + "-" * 60)
    for idx, t in enumerate(trades[-20:], 1):
        print(f"  {idx:<4} {t.direction:<5} {t.mode_tag:<8} {t.confidence:>5.2f} "
              f"{t.open_price:>8.2f} {t.close_price:>8.2f} "
              f"{t.pnl_pct*100:>+7.3f}%  {t.close_reason}")

    if save_json:
        log_path = os.path.join(os.path.dirname(__file__), "logs", "backtest_bpr_xauusd.json")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            json.dump([{
                "direction": t.direction, "mode": t.mode_tag, "order_type": t.order_type,
                "confidence": t.confidence,
                "open_price": t.open_price, "sl_price": t.sl_price, "tp_price": t.tp_price,
                "close_price": t.close_price, "lot_size": t.lot_size,
                "pnl_pct": round(t.pnl_pct*100, 4), "close_reason": t.close_reason,
            } for t in trades], f, indent=2)
        print(f"\n  Trade log: {log_path}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest BPR XAUUSD M15")
    parser.add_argument("--csv",    default="")
    parser.add_argument("--equity", type=float, default=10000.0)
    parser.add_argument("--pipval", type=float, default=1.0)
    parser.add_argument("--step",   type=int,   default=1)
    parser.add_argument("--trail",              action="store_true")
    parser.add_argument("--no-circuit-breaker", action="store_true")
    parser.add_argument("--sweep",              action="store_true",
                        help="Bandingkan 4 kombinasi parameter (step=4 otomatis)")
    # Override manual parameter
    parser.add_argument("--prox",     type=float, default=2.0)
    parser.add_argument("--age",      type=int,   default=80)
    parser.add_argument("--gap",      type=float, default=0.30)
    parser.add_argument("--disp",     type=float, default=0.5)
    parser.add_argument("--rr",       type=float, default=3.0)
    parser.add_argument("--temporal", type=int,   default=48)
    parser.add_argument("--zone-gap",  type=float, default=8.0,
                        help="Near-BPR: max gap antar FVG dalam ATR (default 8.0 untuk XAUUSD)")
    parser.add_argument("--session-filter",            action="store_true",
                        help="Hanya trade saat London 08-12 GMT & NY 13-18 GMT")
    parser.add_argument("--ema-filter",              action="store_true",
                        help="Filter sinyal counter-trend dengan EMA M15")
    parser.add_argument("--ema-period",  type=int,  default=50,
                        help="Period EMA untuk trend filter (default 50)")
    parser.add_argument("--rsi-filter",              action="store_true",
                        help="Konfirmasi RSI sebelum entry LIMIT")
    parser.add_argument("--rsi-buy-max",  type=float, default=55.0,
                        help="BUY: tolak jika RSI >= nilai ini (default 55)")
    parser.add_argument("--rsi-sell-min", type=float, default=45.0,
                        help="SELL: tolak jika RSI <= nilai ini (default 45)")
    parser.add_argument("--adx-filter",               action="store_true",
                        help="Hanya trade saat ADX > threshold (pasar trending)")
    parser.add_argument("--adx-period",   type=int,   default=14,
                        help="Period ADX (default 14)")
    parser.add_argument("--adx-min",      type=float, default=20.0,
                        help="Minimum ADX untuk entry (default 20.0)")
    parser.add_argument("--be",                        action="store_true",
                        help="Aktifkan break-even stop (default: OFF)")
    args = parser.parse_args()

    # Cari CSV
    csv_path = args.csv
    if not csv_path:
        base = os.path.dirname(__file__)
        for c in [
            os.path.join(base, "..", "data", "XAUUSD_GMT+0_NO-DST_M15.csv"),
            os.path.join(base, "..", "data", "XAUUSD_M15.csv"),
            os.path.join(base, "data",       "XAUUSD_M15.csv"),
        ]:
            if os.path.exists(c):
                csv_path = c
                break
    if not csv_path:
        print("CSV tidak ditemukan. Gunakan --csv <path>")
        sys.exit(1)

    print(f"\nMemuat CSV: {csv_path}")
    df = load_csv(csv_path)
    print(f"  {len(df):,} candle | {df['time'].iloc[0]} s/d {df['time'].iloc[-1]}")

    if len(df) < WARMUP + 50:
        print("Data terlalu sedikit."); sys.exit(1)

    records = df.to_dict("records")
    total   = len(records)
    no_cb   = args.no_circuit_breaker

    if args.sweep:
        step = 16  # lebih cepat untuk sweep
        print(f"\nMode SWEEP — {len(SWEEP_CONFIGS)} kombinasi | step={step} | "
              f"trail={'ON' if args.trail else 'OFF'} | HTF filter: OFF (M15 only)\n")
        sweep_results = []
        for cfg in SWEEP_CONFIGS:
            patch_params(cfg['prox'], cfg['age'], cfg['gap'], cfg['disp'],
                         cfg['rr'], cfg['temporal'], cfg['zone_gap'],
                         rsi_filter=args.rsi_filter,
                         rsi_buy_max=args.rsi_buy_max, rsi_sell_min=args.rsi_sell_min,
                         adx_filter=args.adx_filter,
                         adx_period=args.adx_period, adx_min=args.adx_min)
            print(f"  [{cfg['label'].strip()}] prox={cfg['prox']} age={cfg['age']} "
                  f"gap={cfg['gap']} disp={cfg['disp']} RR={cfg['rr']} zone_gap={cfg['zone_gap']}")
            trades, eq_curve, final_eq = run_backtest(
                records, total, args.equity, args.pipval,
                use_trail=args.trail, step=step, no_cb=no_cb, label=cfg['label'].strip(),
                ema_trend_filter=args.ema_filter, ema_period=args.ema_period,
                session_filter=args.session_filter,
                use_be=args.be,
            )
            sweep_results.append((cfg, trades))

        print_sweep_summary(sweep_results)

        # Tampilkan detail untuk combo terbaik (PF tertinggi dengan >= 5 trades)
        best = None
        best_pf = 0.0
        for cfg, trades in sweep_results:
            if len(trades) >= 5:
                gl = abs(sum(t.pnl_pct for t in trades if t.pnl_pct < -0.001))
                gw = abs(sum(t.pnl_pct for t in trades if t.pnl_pct > 0.001))
                pf = gw/gl if gl > 0 else 0.0
                if pf > best_pf:
                    best_pf, best = pf, (cfg, trades)

        if best:
            cfg, trades = best
            patch_params(cfg['prox'], cfg['age'], cfg['gap'], cfg['disp'],
                         cfg['rr'], cfg['temporal'], cfg['zone_gap'],
                         rsi_filter=args.rsi_filter,
                         rsi_buy_max=args.rsi_buy_max, rsi_sell_min=args.rsi_sell_min,
                         adx_filter=args.adx_filter,
                         adx_period=args.adx_period, adx_min=args.adx_min)
            _, eq_curve, final_eq = run_backtest(
                records, total, args.equity, args.pipval,
                use_trail=args.trail, step=1, no_cb=no_cb, label="BEST-detail",
                ema_trend_filter=args.ema_filter, ema_period=args.ema_period,
                session_filter=args.session_filter,
                use_be=args.be,
            )
            print(f"\n--- Detail combo terbaik ({cfg['label'].strip()}) dengan step=1 ---")
            print_report(trades, args.equity, final_eq, eq_curve, cfg, save_json=True)

    else:
        cfg = dict(label="custom", prox=args.prox, age=args.age,
                   gap=args.gap, disp=args.disp, rr=args.rr,
                   temporal=args.temporal, zone_gap=args.zone_gap)
        patch_params(cfg['prox'], cfg['age'], cfg['gap'], cfg['disp'],
                     cfg['rr'], cfg['temporal'], cfg['zone_gap'],
                     rsi_filter=args.rsi_filter,
                     rsi_buy_max=args.rsi_buy_max, rsi_sell_min=args.rsi_sell_min,
                     adx_filter=args.adx_filter,
                     adx_period=args.adx_period, adx_min=args.adx_min)
        rsi_label = (f"ON (RSI<{args.rsi_buy_max}/>{args.rsi_sell_min})"
                     if args.rsi_filter else "OFF")
        adx_label = (f"ON (>{args.adx_min})" if args.adx_filter else "OFF")
        print(f"\nBPR M15 only | prox={cfg['prox']} age={cfg['age']} gap={cfg['gap']} "
              f"disp={cfg['disp']} RR={cfg['rr']} zone_gap={cfg['zone_gap']} | step={args.step} | "
              f"trail=OFF | BE: {'ON' if args.be else 'OFF'} | "
              f"EMA: {'ON('+str(args.ema_period)+')' if args.ema_filter else 'OFF'} | "
              f"RSI: {rsi_label} | ADX: {adx_label} | HTF: OFF\n")
        trades, eq_curve, final_eq = run_backtest(
            records, total, args.equity, args.pipval,
            use_trail=False, step=args.step, no_cb=no_cb,
            ema_trend_filter=args.ema_filter, ema_period=args.ema_period,
            session_filter=args.session_filter,
            use_be=args.be,
        )
        print_report(trades, args.equity, final_eq, eq_curve, cfg)


if __name__ == "__main__":
    main()
