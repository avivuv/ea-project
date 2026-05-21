"""
Strategy 5 — Strong Momentum / Impulse Candle.
Diadopsi dari EA Luma 7.2.1 (ADXNews) — versi post-news impulse detection.

Alih-alih membutuhkan data news real-time, strategy ini mendeteksi
candle dengan body sangat besar (N × ATR) yang menandakan momentum kuat
(bisa dipicu news, breakout, atau institutional move).

Entry logic:
1. Candle body >= MOMENTUM_BODY_ATR_MULT × ATR (impulse candle terdeteksi)
2. ADX >= MOMENTUM_ADX_MIN (trend kuat, bukan random spike)
3. Arah candle sesuai dengan DMI direction
4. MARKET order langsung mengikuti momentum
"""
from __future__ import annotations
import logging
import pandas as pd
import ta
from .base import BaseStrategy, StrategySignal
from config import (
    ADX_PERIOD, ATR_PERIOD,
    MOMENTUM_BODY_ATR_MULT, MOMENTUM_ADX_MIN,
    MOMENTUM_SL_ATR_MULT, MOMENTUM_RR,
)

log = logging.getLogger(__name__)


class StrategyMomentum(BaseStrategy):
    strategy_id = "MOMENTUM"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:
        df = pd.DataFrame(ohlcv)
        df.columns = [c.lower() for c in df.columns]

        if len(df) < ADX_PERIOD + 10:
            return StrategySignal(self.strategy_id, "HOLD", reason="insufficient_data")

        df["atr"]      = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=ATR_PERIOD)
        adx_ind        = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=ADX_PERIOD)
        df["adx"]      = adx_ind.adx()
        df["plus_di"]  = adx_ind.adx_pos()
        df["minus_di"] = adx_ind.adx_neg()

        last = df.iloc[-1]
        atr  = last["atr"]
        adx  = last["adx"]

        if pd.isna(atr) or atr <= 0 or pd.isna(adx):
            return StrategySignal(self.strategy_id, "HOLD", reason="indicator_nan")

        # ── Gate: ADX minimum ────────────────────────────────────────────────
        if adx < MOMENTUM_ADX_MIN:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"adx_too_low:{adx:.1f}<{MOMENTUM_ADX_MIN}",
            )

        # ── Deteksi impulse candle ───────────────────────────────────────────
        body       = abs(last["close"] - last["open"])
        threshold  = MOMENTUM_BODY_ATR_MULT * atr
        is_strong  = body >= threshold

        if not is_strong:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"body_weak:{body:.5f}<{threshold:.5f}({body/atr:.1f}x_atr)",
            )

        is_bull_candle = last["close"] > last["open"]
        dmi_bull       = last["plus_di"] > last["minus_di"]

        # Arah candle harus konsisten dengan DMI
        if is_bull_candle and dmi_bull:
            direction = "BUY"
        elif not is_bull_candle and not dmi_bull:
            direction = "SELL"
        else:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=(
                    f"candle_dmi_conflict|candle:{'bull' if is_bull_candle else 'bear'}"
                    f"|dmi:{'bull' if dmi_bull else 'bear'}"
                ),
            )

        sl_dist    = atr * MOMENTUM_SL_ATR_MULT
        tp_dist    = sl_dist * MOMENTUM_RR
        # Confidence: semakin besar body relatif ATR, semakin kuat sinyal
        confidence = min(body / (atr * 4), 1.0)

        log.info(
            f"[{pair}] MOMENTUM {direction} | body={body:.5f} ({body/atr:.1f}×ATR) "
            f"| adx={adx:.1f} | dmi={'bull' if dmi_bull else 'bear'}"
        )

        return StrategySignal(
            strategy_id=self.strategy_id,
            direction=direction,
            order_type="MARKET",
            sl_distance=round(sl_dist, 5),
            tp_distance=round(tp_dist, 5),
            reason=(
                f"impulse_{direction.lower()}|body:{body/atr:.1f}x_atr"
                f"|adx:{adx:.1f}|dmi:{'bull' if dmi_bull else 'bear'}"
            ),
            confidence=confidence,
        )
