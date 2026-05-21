from __future__ import annotations
import logging
import pandas as pd
import ta
from technical_signal import compute_signal
from .base import BaseStrategy, StrategySignal
from config import (
    ADX_PERIOD, ATR_PERIOD,
    ADX_SPIKE_LOOKBACK, ADX_SPIKE_MIN_INCREASE, ADX_SPIKE_PCT_INCREASE,
    STOCH_K_PERIOD, STOCH_D_PERIOD, STOCH_OVERBOUGHT, STOCH_OVERSOLD,
    EMA_FAST, EMA_CONFIRM_BOUNCE,
)

log = logging.getLogger(__name__)


def _adx_spike(df: pd.DataFrame) -> bool:
    adx = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=ADX_PERIOD).adx()
    now = adx.iloc[-1]
    ref = adx.iloc[-1 - ADX_SPIKE_LOOKBACK]
    if pd.isna(ref) or ref <= 0:
        return False
    return now >= ref + ADX_SPIKE_MIN_INCREASE or now >= ref * ADX_SPIKE_PCT_INCREASE


def _stoch_confirm(df: pd.DataFrame, direction: str) -> bool:
    stoch  = ta.momentum.StochasticOscillator(
        df["high"], df["low"], df["close"],
        window=STOCH_K_PERIOD, smooth_window=STOCH_D_PERIOD,
    )
    k, d = stoch.stoch(), stoch.stoch_signal()
    lk, ld = k.iloc[-1], d.iloc[-1]
    pk, pd_ = k.iloc[-2], d.iloc[-2]
    if any(pd.isna(v) for v in [lk, ld, pk, pd_]):
        return False
    if direction == "BUY":
        return (pk < STOCH_OVERSOLD or pd_ < STOCH_OVERSOLD) and (pk <= pd_ and lk > ld)
    else:
        return (pk > STOCH_OVERBOUGHT or pd_ > STOCH_OVERBOUGHT) and (pk >= pd_ and lk < ld)


class StrategyEMA(BaseStrategy):
    """
    Strategy 1 — EMA Trend Following + ADX Spike + Stochastic confirmation.
    Gate utama: EMA/RSI/ADX/candle/volume di technical_signal.py.
    ADX spike dan Stochastic crossover menambah confidence, bukan memblokir.
    """
    strategy_id = "EMA_TREND"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:
        sig = compute_signal(ohlcv, pair=pair, htf_ohlcv=htf_ohlcv)

        log.info(
            f"[{pair}] EMA | signal={sig.direction} | RSI={sig.rsi} | ATR={sig.atr} "
            f"| ADX={sig.adx} | EMA50={sig.ema_fast} | EMA200={sig.ema_slow} | reason={sig.reason}"
        )

        if sig.direction == "HOLD":
            return StrategySignal(strategy_id=self.strategy_id, direction="HOLD", reason=sig.reason)

        # ── Confidence base dari ADX ─────────────────────────────────────────
        confidence = min(sig.adx / 50.0, 1.0) if sig.adx > 0 else 0.3

        # ── Bonus konfirmasi: ADX spike + Stochastic ─────────────────────────
        df = pd.DataFrame(ohlcv)
        df.columns = [c.lower() for c in df.columns]

        extras = []
        spike = _adx_spike(df)
        stoch = _stoch_confirm(df, sig.direction)

        if spike:
            confidence = min(confidence + 0.10, 1.0)
            extras.append("adx_spike")
        if stoch:
            confidence = min(confidence + 0.10, 1.0)
            extras.append("stoch_confirm")

        # ── EMA50 Bounce / Rejection Confirmation ────────────────────────────
        bounce_confirmed = False
        if EMA_CONFIRM_BOUNCE and len(df) >= 2:
            ema50 = ta.trend.ema_indicator(df["close"], window=EMA_FAST).iloc[-1]
            if not pd.isna(ema50):
                prev = df.iloc[-2]
                curr = df.iloc[-1]
                if sig.direction == "BUY":
                    # Harga turun menyentuh EMA50 lalu reject ke atas
                    bounce_confirmed = prev["low"] <= ema50 and curr["close"] > ema50
                else:
                    # Harga naik menyentuh EMA50 lalu reject ke bawah
                    bounce_confirmed = prev["high"] >= ema50 and curr["close"] < ema50

            if bounce_confirmed:
                confidence = min(confidence + 0.15, 1.0)
                extras.append("ema_bounce")
                log.info(f"[{pair}] EMA_TREND bounce confirmed at EMA50={ema50:.5f}")
            elif EMA_CONFIRM_BOUNCE:
                log.info(f"[{pair}] EMA_TREND: no bounce at EMA50 — HOLD")
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    direction="HOLD",
                    reason=sig.reason + "|no_ema_bounce",
                )

        reason = sig.reason + ("|" + "+".join(extras) if extras else "")

        return StrategySignal(
            strategy_id=self.strategy_id,
            direction=sig.direction,
            order_type="MARKET",
            entry_price=0.0,
            sl_distance=sig.sl_distance,
            tp_distance=sig.tp_distance,
            reason=reason,
            confidence=confidence,
        )
