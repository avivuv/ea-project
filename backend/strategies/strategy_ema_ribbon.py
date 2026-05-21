"""
Strategy 9 — EMA Ribbon Fast Cross (Scalping).
Entry saat EMA5 cross EMA20, konfirmasi ADX > threshold.
SL/TP lebih ketat dari strategi trend utama.
"""
from __future__ import annotations
import logging
import pandas as pd
import ta
from .base import BaseStrategy, StrategySignal
from config import ATR_PERIOD, ADX_PERIOD

log = logging.getLogger(__name__)

EMA_FAST   = 5
EMA_MED    = 20
ADX_MIN    = 15.0
SL_MULT    = 1.5
TP_MULT    = 2.5


class StrategyEMARibbon(BaseStrategy):
    strategy_id = "EMA_RIBBON"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:
        df = pd.DataFrame(ohlcv)
        df.columns = [c.lower() for c in df.columns]

        min_bars = max(EMA_MED, ATR_PERIOD, ADX_PERIOD) + 5
        if len(df) < min_bars:
            return StrategySignal(self.strategy_id, "HOLD", reason="insufficient_data")

        df["ema_fast"] = ta.trend.ema_indicator(df["close"], window=EMA_FAST)
        df["ema_med"]  = ta.trend.ema_indicator(df["close"], window=EMA_MED)
        df["atr"]      = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], window=ATR_PERIOD
        )
        adx_ind = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=ADX_PERIOD)
        df["adx"] = adx_ind.adx()

        last  = df.iloc[-1]
        prev  = df.iloc[-2]

        atr = last["atr"]
        adx = last["adx"]

        if pd.isna(atr) or atr <= 0 or pd.isna(adx):
            return StrategySignal(self.strategy_id, "HOLD", reason="indicator_nan")

        if adx < ADX_MIN:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"adx_too_low:{adx:.1f}<{ADX_MIN}",
            )

        ema_fast_now  = last["ema_fast"]
        ema_med_now   = last["ema_med"]
        ema_fast_prev = prev["ema_fast"]
        ema_med_prev  = prev["ema_med"]

        sl_dist = round(atr * SL_MULT, 5)
        tp_dist = round(atr * TP_MULT, 5)

        # BUY: EMA5 cross above EMA20 (prev below, now above)
        if ema_fast_prev <= ema_med_prev and ema_fast_now > ema_med_now:
            confidence = min(adx / 60, 0.85)
            log.info(
                f"[{pair}] EMA_RIBBON BUY | ema5={ema_fast_now:.5f} cross above ema20={ema_med_now:.5f}"
                f" | adx={adx:.1f} | atr={atr:.5f}"
            )
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="BUY",
                order_type="MARKET",
                sl_distance=sl_dist,
                tp_distance=tp_dist,
                reason=f"ema_ribbon_bull_cross|ema5:{ema_fast_now:.5f}>ema20:{ema_med_now:.5f}|adx:{adx:.1f}",
                confidence=confidence,
            )

        # SELL: EMA5 cross below EMA20
        if ema_fast_prev >= ema_med_prev and ema_fast_now < ema_med_now:
            confidence = min(adx / 60, 0.85)
            log.info(
                f"[{pair}] EMA_RIBBON SELL | ema5={ema_fast_now:.5f} cross below ema20={ema_med_now:.5f}"
                f" | adx={adx:.1f} | atr={atr:.5f}"
            )
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="SELL",
                order_type="MARKET",
                sl_distance=sl_dist,
                tp_distance=tp_dist,
                reason=f"ema_ribbon_bear_cross|ema5:{ema_fast_now:.5f}<ema20:{ema_med_now:.5f}|adx:{adx:.1f}",
                confidence=confidence,
            )

        return StrategySignal(
            self.strategy_id, "HOLD",
            reason=f"no_cross|ema5:{ema_fast_now:.5f}|ema20:{ema_med_now:.5f}|adx:{adx:.1f}",
        )
