"""
Strategy 11 — Opening Range Breakout (ORB).

Opening range = high/low dari ORB_RANGE_CANDLES M15 pertama setelah sesi buka.
Signal = close candle di luar range → entry MARKET.

Session UTC:
- London open 08:00: EURUSD, GBPUSD, USDJPY, XAUUSD, EURCHF
- NYSE open  13:30: US500, USTEC

SL = sisi berlawanan range + buffer ATR.
TP = sl_distance × ORB_RR  (guarantees theoretical RR = ORB_RR:1).
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

import pandas as pd
import ta

from .base import BaseStrategy, StrategySignal
from config import (
    ATR_PERIOD,
    ORB_RANGE_CANDLES,
    ORB_MAX_BREAKOUT_CANDLES,
    ORB_MIN_RANGE_ATR,
    ORB_SL_BUFFER_ATR,
    ORB_RR,
    ORB_SESSION_UTC,
)

log = logging.getLogger(__name__)


class StrategyORB(BaseStrategy):
    """
    Strategy 11 — Opening Range Breakout (ORB).
    MARKET order saat harga break out dari range awal sesi.
    """
    strategy_id = "ORB"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:
        df = pd.DataFrame(ohlcv)
        df.columns = [c.lower() for c in df.columns]

        if len(df) < 50:
            return StrategySignal(self.strategy_id, "HOLD", reason="insufficient_data")

        df["atr"] = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], window=ATR_PERIOD
        )
        atr = df["atr"].iloc[-1]
        if pd.isna(atr) or atr <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="atr_nan")

        # ── Tentukan sesi pair ──────────────────────────────────────────────
        session_hour, session_min = ORB_SESSION_UTC.get(pair.upper(), (8, 0))

        # Gunakan timestamp candle terakhir (support backtest & live)
        # Di live trading: candle terakhir = candle tertutup terbaru (max 15 menit lalu)
        try:
            raw_ts = df["time"].iloc[-1]
            ts = pd.Timestamp(raw_ts)
            now_utc = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None \
                      else ts.tz_convert("UTC").to_pydatetime()
            if hasattr(now_utc, "to_pydatetime"):
                now_utc = now_utc.to_pydatetime()
        except Exception:
            now_utc = datetime.now(timezone.utc)

        session_open = now_utc.replace(
            hour=session_hour, minute=session_min, second=0, microsecond=0
        )

        if now_utc < session_open:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason="orb_session_not_open_yet"
            )

        minutes_elapsed  = (now_utc - session_open).total_seconds() / 60
        bars_elapsed     = int(minutes_elapsed / 15)   # M15 bars sejak sesi buka

        # Masih dalam periode pembentukan range
        if bars_elapsed < ORB_RANGE_CANDLES:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"orb_range_forming:{bars_elapsed}/{ORB_RANGE_CANDLES}bars"
            )

        bars_after_range = bars_elapsed - ORB_RANGE_CANDLES

        # Window breakout sudah lewat
        if bars_after_range > ORB_MAX_BREAKOUT_CANDLES:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"orb_expired:{bars_after_range}bars_after_range>max{ORB_MAX_BREAKOUT_CANDLES}"
            )

        # ── Ambil candle opening range dari history ─────────────────────────
        # bars[-1] = current, bars_elapsed bars ago = candle pertama sesi
        range_start = -(bars_elapsed + 1)
        range_end   = range_start + ORB_RANGE_CANDLES  # negatif atau 0

        if abs(range_start) > len(df):
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason="orb_range_out_of_history"
            )

        range_df   = df.iloc[range_start:range_end if range_end < 0 else None]
        range_high = range_df["high"].max()
        range_low  = range_df["low"].min()
        range_size = range_high - range_low

        # ── Validasi: range harus cukup besar ──────────────────────────────
        if range_size < ORB_MIN_RANGE_ATR * atr:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"orb_range_too_small:{range_size:.5f}<{ORB_MIN_RANGE_ATR * atr:.5f}(min)"
            )

        # ── Cek breakout pada candle terbaru (close di luar range) ──────────
        curr_close = df["close"].iloc[-1]

        if curr_close > range_high:
            direction = "BUY"
        elif curr_close < range_low:
            direction = "SELL"
        else:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=(
                    f"orb_no_breakout|close:{curr_close:.5f}"
                    f"|range:[{range_low:.5f}~{range_high:.5f}]"
                )
            )

        # ── Hitung SL & TP ──────────────────────────────────────────────────
        buf = ORB_SL_BUFFER_ATR * atr

        if direction == "BUY":
            sl_distance = (curr_close - range_low) + buf
            tp_distance = sl_distance * ORB_RR
        else:
            sl_distance = (range_high - curr_close) + buf
            tp_distance = sl_distance * ORB_RR

        if sl_distance <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="sl_zero")

        # ── Confidence: makin awal breakout + range makin besar → lebih tinggi
        time_score  = 1.0 - (bars_after_range / (ORB_MAX_BREAKOUT_CANDLES + 1)) * 0.4
        range_score = min(1.0, range_size / (atr * 1.5))
        confidence  = round(min(0.90, 0.65 * time_score + 0.15 * range_score), 2)

        log.info(
            f"[{pair}] ORB {direction} | range=[{range_low:.5f}~{range_high:.5f}] "
            f"size={range_size:.5f} | bars_after={bars_after_range} | conf={confidence:.2f}"
        )

        return StrategySignal(
            strategy_id=self.strategy_id,
            direction=direction,
            order_type="MARKET",
            entry_price=0.0,
            sl_distance=round(sl_distance, 5),
            tp_distance=round(tp_distance, 5),
            reason=(
                f"orb_{'bull' if direction == 'BUY' else 'bear'}"
                f"|range:[{range_low:.5f}~{range_high:.5f}]"
                f"|size:{range_size:.5f}"
                f"|bars_after:{bars_after_range}"
            ),
            confidence=confidence,
        )
