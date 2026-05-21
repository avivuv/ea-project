"""
Strategy 4 — CHoCH + Order Block (pending LIMIT order).
Diadopsi dari SnR 2.2.4 (Pending Order).

Entry logic:
1. Deteksi CHoCH (Change of Character): perubahan struktur swing high/low
2. Cari Order Block terbaik searah dengan CHoCH
3. Pasang LIMIT order di level OB (price diharapkan pull-back ke OB sebelum lanjut)
4. SL: di luar OB + buffer, TP: SL × RR
"""
from __future__ import annotations
import logging
import pandas as pd
import ta
from .base import BaseStrategy, StrategySignal
from choch_detector import detect_choch, find_best_order_block
from config import (
    ATR_PERIOD,
    CHOCH_SWING_PERIOD, CHOCH_OB_BODY_MIN, CHOCH_OB_LOOKBACK,
    CHOCH_MAX_OB_DIST_ATR, CHOCH_OB_SL_BUFFER_ATR, CHOCH_RR,
)

log = logging.getLogger(__name__)


class StrategyCHoCHOB(BaseStrategy):
    strategy_id = "CHOCH_OB"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:
        df = pd.DataFrame(ohlcv)
        df.columns = [c.lower() for c in df.columns]

        if len(df) < CHOCH_SWING_PERIOD * 4 + 10:
            return StrategySignal(self.strategy_id, "HOLD", reason="insufficient_data")

        df["atr"] = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=ATR_PERIOD)
        atr = df["atr"].iloc[-1]

        if pd.isna(atr) or atr <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="atr_nan")

        curr_price = df["close"].iloc[-1]

        # ── Deteksi CHoCH ────────────────────────────────────────────────────
        bull_choch, bear_choch = detect_choch(df, period=CHOCH_SWING_PERIOD)

        if not bull_choch and not bear_choch:
            return StrategySignal(self.strategy_id, "HOLD", reason="no_choch")

        direction = "BUY" if bull_choch else "SELL"

        # ── Cari Order Block terbaik ─────────────────────────────────────────
        ob = find_best_order_block(
            df, direction,
            lookback=CHOCH_OB_LOOKBACK,
            body_min_ratio=CHOCH_OB_BODY_MIN,
        )

        if ob is None:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"choch_{direction.lower()}_no_ob",
            )

        # ── Validasi jarak OB ke harga sekarang ─────────────────────────────
        ob_mid     = (ob.top + ob.bottom) / 2
        ob_dist    = abs(curr_price - ob_mid)
        max_dist   = CHOCH_MAX_OB_DIST_ATR * atr

        if ob_dist > max_dist:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"ob_too_far|dist:{ob_dist:.5f}|max:{max_dist:.5f}",
            )

        # ── Hitung entry, SL, TP ─────────────────────────────────────────────
        ob_height = ob.top - ob.bottom
        buf       = CHOCH_OB_SL_BUFFER_ATR * atr

        if direction == "BUY":
            # Entry di atas OB (pull-back ke batas atas zone)
            entry_price = ob.top
            sl_distance = ob_height + buf
        else:
            # Entry di bawah OB (pull-back ke batas bawah zone)
            entry_price = ob.bottom
            sl_distance = ob_height + buf

        if sl_distance <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="sl_zero")

        tp_distance = sl_distance * CHOCH_RR
        confidence  = min(ob.score / 10.0, 1.0)

        log.info(
            f"[{pair}] CHOCH_OB {direction} | choch={'bull' if bull_choch else 'bear'} "
            f"| OB=[{ob.bottom:.5f}~{ob.top:.5f}] score={ob.score:.2f} bars_ago={ob.bars_ago} "
            f"| entry={entry_price:.5f} sl={sl_distance:.5f} tp={tp_distance:.5f}"
        )

        return StrategySignal(
            strategy_id=self.strategy_id,
            direction=direction,
            order_type="LIMIT",
            entry_price=round(entry_price, 5),
            sl_distance=round(sl_distance, 5),
            tp_distance=round(tp_distance, 5),
            reason=(
                f"choch_{'bull' if bull_choch else 'bear'}+ob_score{ob.score:.1f}"
                f"|ob_age:{ob.bars_ago}bars|entry:{entry_price:.5f}"
            ),
            confidence=confidence,
        )
