"""
Strategy 5 — Bollinger Bands Mean Reversion.

Berlawanan arah dengan trend strategy — menangkap koreksi/reversal
saat harga menyentuh batas ekstrem Bollinger Bands.

Entry logic:
1. Price menyentuh/melewati lower band (BUY) atau upper band (SELL)
2. Candle berikutnya close kembali di dalam band (konfirmasi reversal)
3. RSI ekstrem: RSI < BB_RSI_OVERSOLD (BUY) atau RSI > BB_RSI_OVERBOUGHT (SELL)
4. MARKET order mengikuti arah reversal

Target (TP): middle band (SMA20) — mean reversion ke rata-rata
SL: di luar band + ATR buffer
"""
from __future__ import annotations
import logging
import pandas as pd
import ta
from .base import BaseStrategy, StrategySignal
from config import (
    ATR_PERIOD, RSI_PERIOD,
    BB_PERIOD, BB_STD, BB_RSI_OVERSOLD, BB_RSI_OVERBOUGHT,
    BB_SL_ATR_MULT, BB_RR,
)

log = logging.getLogger(__name__)


class StrategyBBReversion(BaseStrategy):
    """
    Strategy 5 — Bollinger Bands Mean Reversion.
    Satu-satunya strategy yang bersifat counter-trend/reversal.
    """
    strategy_id = "BB_REVERSION"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:
        df = pd.DataFrame(ohlcv)
        df.columns = [c.lower() for c in df.columns]

        if len(df) < BB_PERIOD + ATR_PERIOD + 5:
            return StrategySignal(self.strategy_id, "HOLD", reason="insufficient_data")

        # ── Indikator ────────────────────────────────────────────────────────
        bb         = ta.volatility.BollingerBands(df["close"], window=BB_PERIOD, window_dev=BB_STD)
        df["bb_upper"]  = bb.bollinger_hband()
        df["bb_lower"]  = bb.bollinger_lband()
        df["bb_mid"]    = bb.bollinger_mavg()
        df["rsi"]       = ta.momentum.rsi(df["close"], window=RSI_PERIOD)
        df["atr"]       = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=ATR_PERIOD)

        last = df.iloc[-1]
        prev = df.iloc[-2]

        if any(pd.isna(last[c]) for c in ["bb_upper", "bb_lower", "bb_mid", "rsi", "atr"]):
            return StrategySignal(self.strategy_id, "HOLD", reason="indicator_nan")

        atr = last["atr"]
        if atr <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="atr_zero")

        # ── BUY: price cross kembali ke atas lower band dari bawah ───────────
        # Candle sebelumnya menyentuh/menembus lower band, sekarang kembali masuk
        prev_touched_lower = prev["low"] <= prev["bb_lower"]
        curr_back_inside   = last["close"] > last["bb_lower"]
        rsi_oversold       = last["rsi"] < BB_RSI_OVERSOLD

        if prev_touched_lower and curr_back_inside and rsi_oversold:
            # TP = jarak dari entry ke middle band
            tp_dist = last["bb_mid"] - last["close"]
            if tp_dist <= 0:
                tp_dist = (last["bb_upper"] - last["bb_lower"]) * 0.5

            sl_dist    = atr * BB_SL_ATR_MULT
            confidence = min((BB_RSI_OVERSOLD - last["rsi"]) / BB_RSI_OVERSOLD, 1.0)

            log.info(
                f"[{pair}] BB_REVERSION BUY | price={last['close']:.5f} "
                f"lower={last['bb_lower']:.5f} mid={last['bb_mid']:.5f} | RSI={last['rsi']:.1f}"
            )
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="BUY",
                order_type="MARKET",
                sl_distance=round(sl_dist, 5),
                tp_distance=round(tp_dist, 5),
                reason=f"bb_lower_reversion|rsi:{last['rsi']:.1f}|lower:{last['bb_lower']:.5f}",
                confidence=confidence,
            )

        # ── SELL: price cross kembali ke bawah upper band dari atas ──────────
        prev_touched_upper = prev["high"] >= prev["bb_upper"]
        curr_back_inside   = last["close"] < last["bb_upper"]
        rsi_overbought     = last["rsi"] > BB_RSI_OVERBOUGHT

        if prev_touched_upper and curr_back_inside and rsi_overbought:
            tp_dist = last["close"] - last["bb_mid"]
            if tp_dist <= 0:
                tp_dist = (last["bb_upper"] - last["bb_lower"]) * 0.5

            sl_dist    = atr * BB_SL_ATR_MULT
            confidence = min((last["rsi"] - BB_RSI_OVERBOUGHT) / (100 - BB_RSI_OVERBOUGHT), 1.0)

            log.info(
                f"[{pair}] BB_REVERSION SELL | price={last['close']:.5f} "
                f"upper={last['bb_upper']:.5f} mid={last['bb_mid']:.5f} | RSI={last['rsi']:.1f}"
            )
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="SELL",
                order_type="MARKET",
                sl_distance=round(sl_dist, 5),
                tp_distance=round(tp_dist, 5),
                reason=f"bb_upper_reversion|rsi:{last['rsi']:.1f}|upper:{last['bb_upper']:.5f}",
                confidence=confidence,
            )

        return StrategySignal(
            self.strategy_id, "HOLD",
            reason=(
                f"no_bb_touch|rsi:{last['rsi']:.1f}"
                f"|low_vs_lower:{last['low']:.5f}vs{last['bb_lower']:.5f}"
                f"|high_vs_upper:{last['high']:.5f}vs{last['bb_upper']:.5f}"
            ),
        )
