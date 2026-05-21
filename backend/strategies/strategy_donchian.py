"""
Strategy 8 — Donchian Channel Breakout.
Diadaptasi dari Turtle Trading System (Richard Dennis, 1983).

Prinsip: jika price break di atas/bawah N-period high/low,
ini sinyal trend baru yang kuat — ikuti arahnya.

Entry logic:
1. Close candle break di atas Donchian upper (N-period high) → BUY
2. Close candle break di bawah Donchian lower (N-period low) → SELL
3. ATR minimum: pasar tidak flat/choppy
4. MARKET order mengikuti breakout

Berbeda dari EMA (lagging trend) — Donchian menangkap momen
PERTAMA KALI price melampaui level historis.
"""
from __future__ import annotations
import logging
import pandas as pd
import ta
from .base import BaseStrategy, StrategySignal
from config import (
    ATR_PERIOD,
    DONCHIAN_PERIOD, DONCHIAN_ATR_MIN,
    DONCHIAN_SL_ATR_MULT, DONCHIAN_RR,
)

log = logging.getLogger(__name__)


class StrategyDonchian(BaseStrategy):
    """
    Strategy 8 — Donchian Channel Breakout.
    Entry saat price pertama kali break di atas/bawah N-candle high/low.
    """
    strategy_id = "DONCHIAN"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:
        df = pd.DataFrame(ohlcv)
        df.columns = [c.lower() for c in df.columns]

        if len(df) < DONCHIAN_PERIOD + ATR_PERIOD + 5:
            return StrategySignal(self.strategy_id, "HOLD", reason="insufficient_data")

        df["atr"] = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=ATR_PERIOD)

        atr = df["atr"].iloc[-1]
        if pd.isna(atr) or atr <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="atr_nan")

        # ── Donchian channel ─────────────────────────────────────────────────
        # Exclude candle terakhir dari channel (baru saja close, bisa self-referential)
        channel_df   = df.iloc[-DONCHIAN_PERIOD - 1: -1]
        upper        = channel_df["high"].max()   # N-period high
        lower        = channel_df["low"].min()    # N-period low

        last_close   = df["close"].iloc[-1]
        prev_close   = df["close"].iloc[-2]

        # ── Gate: ATR minimum ────────────────────────────────────────────────
        channel_size = upper - lower
        if channel_size < DONCHIAN_ATR_MIN * atr:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"channel_too_narrow:{channel_size:.5f}<{DONCHIAN_ATR_MIN * atr:.5f}",
            )

        sl_dist    = atr * DONCHIAN_SL_ATR_MULT
        tp_dist    = sl_dist * DONCHIAN_RR

        # ── BUY breakout: close melampaui N-period high ──────────────────────
        # prev_close masih di dalam channel (breakout baru terjadi)
        if last_close > upper and prev_close <= upper:
            confidence = min(channel_size / (atr * 5), 1.0)
            log.info(
                f"[{pair}] DONCHIAN BUY | close={last_close:.5f} > upper={upper:.5f} "
                f"| channel={channel_size:.5f} | atr={atr:.5f}"
            )
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="BUY",
                order_type="MARKET",
                sl_distance=round(sl_dist, 5),
                tp_distance=round(tp_dist, 5),
                reason=f"donchian_breakout_up|close:{last_close:.5f}>upper:{upper:.5f}",
                confidence=confidence,
            )

        # ── SELL breakout: close menembus N-period low ───────────────────────
        if last_close < lower and prev_close >= lower:
            confidence = min(channel_size / (atr * 5), 1.0)
            log.info(
                f"[{pair}] DONCHIAN SELL | close={last_close:.5f} < lower={lower:.5f} "
                f"| channel={channel_size:.5f} | atr={atr:.5f}"
            )
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="SELL",
                order_type="MARKET",
                sl_distance=round(sl_dist, 5),
                tp_distance=round(tp_dist, 5),
                reason=f"donchian_breakout_down|close:{last_close:.5f}<lower:{lower:.5f}",
                confidence=confidence,
            )

        return StrategySignal(
            self.strategy_id, "HOLD",
            reason=f"inside_channel|close:{last_close:.5f}|upper:{upper:.5f}|lower:{lower:.5f}",
        )
