from __future__ import annotations
import logging
import pandas as pd
import ta
from strategies.base import StrategySignal, HOLD_SIGNAL
from strategies.strategy_ema import StrategyEMA
from strategies.strategy_snd import StrategySND
from strategies.strategy_fvg import StrategyFVG
from strategies.strategy_bumi import StrategyBUMI
from strategies.strategy_obfvg import StrategyOBFVG
from strategies.strategy_ob_confirm import StrategyOBConfirm
from strategies.strategy_bpr import StrategyBPR
from config import MIN_SIGNAL_CONF, MIN_STRATEGIES_CONFIRM, SINGLE_HIGH_CONF, ATR_PERIOD, BUMI_ENABLED, OBFVG_ENABLED, OBFVG_DISABLED_PAIRS, OB_CONFIRM_ENABLED, OB_CONFIRM_DISABLED_PAIRS, BPR_ENABLED, BPR_DISABLED_PAIRS
from sr_detector import find_sr_levels, near_sr_level

SR_CONFLUENCE_BONUS     = 0.10   # bonus confidence jika entry dekat S/R level
SR_CONFLUENCE_TOLERANCE = 0.5    # dalam N × ATR dari S/R level

log = logging.getLogger(__name__)

_strategies = [
    StrategyEMA(),                                      # EMA + ADX Spike + Stochastic
    StrategyFVG(),                                      # Fair Value Gap
    *([StrategyBUMI()]      if BUMI_ENABLED      else []),  # BUMI 4 MA Cross (opsional)
    *([StrategyOBFVG()]     if OBFVG_ENABLED     else []),  # OB+FVG confluence (opsional)
    *([StrategyOBConfirm()] if OB_CONFIRM_ENABLED else []), # OB fresh + candle confirmation
    *([StrategyBPR()]       if BPR_ENABLED       else []), # Balanced Price Range (M15)
]


def run_all(
    ohlcv:     list,
    pair:      str,
    htf_ohlcv: list | None = None,
    h4_ohlcv:  list | None = None,
) -> StrategySignal:
    """
    Jalankan semua strategy, kembalikan sinyal terbaik.

    Aturan agregasi:
    - Satu sinyal aktif  → langsung pakai
    - Beberapa sinyal SEARAH → pakai yang confidence tertinggi (bonus +0.1)
    - Sinyal KONFLIK (BUY vs SELL) → HOLD, tunggu konfirmasi
    """
    # Pre-compute S/R levels dan ATR sekali untuk semua strategy
    try:
        _df  = pd.DataFrame(ohlcv)
        _df.columns = [c.lower() for c in _df.columns]
        _atr_s = ta.volatility.average_true_range(_df["high"], _df["low"], _df["close"], window=ATR_PERIOD)
        _atr   = float(_atr_s.iloc[-1]) if not pd.isna(_atr_s.iloc[-1]) else 0.0
        _close = float(_df["close"].iloc[-1])
        _sr_levels = find_sr_levels(_df)
    except Exception:
        _atr, _close, _sr_levels = 0.0, 0.0, []

    active: list[StrategySignal] = []

    for strategy in _strategies:
        if strategy.strategy_id == "OBFVG" and pair in OBFVG_DISABLED_PAIRS:
            log.info(f"[{pair}] OBFVG skipped (disabled for this pair)")
            continue
        if strategy.strategy_id == "BPR" and pair.upper() in BPR_DISABLED_PAIRS:
            log.info(f"[{pair}] BPR skipped (disabled for this pair)")
            continue
        if strategy.strategy_id == "OB_CONFIRM" and pair.upper() in OB_CONFIRM_DISABLED_PAIRS:
            log.info(f"[{pair}] OB_CONFIRM skipped (disabled for this pair)")
            continue
        try:
            sig = strategy.compute(ohlcv, pair, htf_ohlcv=htf_ohlcv, h4_ohlcv=h4_ohlcv)
            log.info(f"[{pair}] {strategy.strategy_id}: {sig.direction} | conf={sig.confidence:.2f} | {sig.reason}")
            if sig.is_active:
                if sig.confidence >= MIN_SIGNAL_CONF:
                    # Bonus confidence jika entry dekat S/R level
                    entry = sig.entry_price if sig.entry_price > 0 else _close
                    if _atr > 0 and near_sr_level(entry, _sr_levels, _atr, SR_CONFLUENCE_TOLERANCE):
                        new_conf = min(sig.confidence + SR_CONFLUENCE_BONUS, 1.0)
                        sig = StrategySignal(
                            strategy_id=sig.strategy_id,
                            direction=sig.direction,
                            order_type=sig.order_type,
                            entry_price=sig.entry_price,
                            sl_distance=sig.sl_distance,
                            tp_distance=sig.tp_distance,
                            reason=sig.reason + "|sr_conf",
                            confidence=new_conf,
                        )
                        log.info(f"[{pair}] {strategy.strategy_id} S/R confluence -> conf={new_conf:.2f}")
                    active.append(sig)
                else:
                    log.info(f"[{pair}] {strategy.strategy_id} filtered: conf={sig.confidence:.2f} < min={MIN_SIGNAL_CONF}")
        except Exception as e:
            log.warning(f"[{pair}] Strategy {strategy.strategy_id} error: {e}")

    if not active:
        return HOLD_SIGNAL

    directions = {s.direction for s in active}

    # Konflik BUY vs SELL → HOLD
    if "BUY" in directions and "SELL" in directions:
        reasons = " | ".join(f"{s.strategy_id}:{s.direction}" for s in active)
        log.info(f"[{pair}] strategy conflict -> HOLD | {reasons}")
        return StrategySignal(
            strategy_id="runner",
            direction="HOLD",
            reason=f"strategy_conflict:{reasons}",
        )

    # Wajib minimal MIN_STRATEGIES_CONFIRM strategi searah,
    # kecuali satu sinyal memiliki confidence >= SINGLE_HIGH_CONF
    best = max(active, key=lambda s: s.confidence)
    if len(active) < MIN_STRATEGIES_CONFIRM and best.confidence < SINGLE_HIGH_CONF:
        log.info(
            f"[{pair}] HOLD — needs_confirmation | {best.strategy_id} conf={best.confidence:.2f} "
            f"(require {MIN_STRATEGIES_CONFIRM}+ strategies or conf>={SINGLE_HIGH_CONF})"
        )
        return StrategySignal(
            strategy_id="runner",
            direction="HOLD",
            reason=f"needs_confirmation:{best.strategy_id}:conf{best.confidence:.2f}",
        )

    # Semua searah → ambil yang confidence tertinggi, beri bonus jika >1 konfirmasi
    if len(active) > 1:
        best = StrategySignal(
            strategy_id=best.strategy_id,
            direction=best.direction,
            order_type=best.order_type,
            entry_price=best.entry_price,
            sl_distance=best.sl_distance,
            tp_distance=best.tp_distance,
            reason=best.reason + f"|confirmed_by_{len(active)}_strategies",
            confidence=min(best.confidence + 0.1, 1.0),
        )

    return best
