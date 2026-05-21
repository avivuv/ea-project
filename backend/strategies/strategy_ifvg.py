"""
Strategy 10 — Inverted Fair Value Gap (iFVG).

iFVG terbentuk ketika harga menembus MELEWATI zona FVG (bukan hanya masuk).
FVG bullish yang tertembus ke bawah → flip jadi resistance → SELL.
FVG bearish yang tertembus ke atas  → flip jadi support   → BUY.

Entry: LIMIT saat price retest zona iFVG dari arah berlawanan.
"""
from __future__ import annotations
import logging
import pandas as pd
import ta
from .base import BaseStrategy, StrategySignal
from fvg_detector import detect_fvg
from config import (
    ATR_PERIOD,
    IFVG_LOOKBACK, IFVG_MIN_GAP_ATR, IFVG_PROXIMITY_ATR,
    IFVG_SL_BUFFER_ATR, IFVG_SL_BUFFER_ATR_BY_PAIR, IFVG_RR, IFVG_MAX_AGE_BARS,
)

log = logging.getLogger(__name__)


class StrategyIFVG(BaseStrategy):
    strategy_id = "IFVG"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:
        df = pd.DataFrame(ohlcv)
        df.columns = [c.lower() for c in df.columns]

        if len(df) < IFVG_LOOKBACK + 10:
            return StrategySignal(self.strategy_id, "HOLD", reason="insufficient_data")

        df["atr"] = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], window=ATR_PERIOD
        )

        atr = df["atr"].iloc[-1]
        if pd.isna(atr) or atr <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="atr_nan")

        min_gap  = IFVG_MIN_GAP_ATR * atr
        curr     = df["close"].iloc[-1]
        max_dist = IFVG_PROXIMITY_ATR * atr
        sl_buf_mult = IFVG_SL_BUFFER_ATR_BY_PAIR.get(pair.upper(), IFVG_SL_BUFFER_ATR)
        buf      = sl_buf_mult * atr
        n        = len(df)

        all_zones = detect_fvg(df, lookback=IFVG_LOOKBACK, min_gap=min_gap)

        best_sell = None  # iFVG resistance (dari bullish FVG yang diinvert)
        best_buy  = None  # iFVG support   (dari bearish FVG yang diinvert)

        for zone in all_zones:
            if zone.fresh:
                continue  # FVG masih intact, belum bisa jadi iFVG
            if zone.bars_ago > IFVG_MAX_AGE_BARS:
                continue  # zone terlalu tua

            fvg_idx = n - 1 - zone.bars_ago
            if fvg_idx + 1 >= n:
                continue

            subsequent = df.iloc[fvg_idx + 1:]

            if zone.direction == "BUY":
                # Bullish FVG diinvert jika price pernah close di bawah gap_bottom
                if not bool((subsequent["close"] < zone.bottom).any()):
                    continue

                # iFVG resistance: price naik kembali ke zona → SELL LIMIT
                dist = zone.bottom - curr
                if curr < zone.top and dist <= max_dist:
                    if best_sell is None or dist < best_sell["dist"]:
                        best_sell = {"zone": zone, "dist": max(0.0, dist)}

            else:  # SELL FVG
                # Bearish FVG diinvert jika price pernah close di atas gap_top
                if not bool((subsequent["close"] > zone.top).any()):
                    continue

                # iFVG support: price turun kembali ke zona → BUY LIMIT
                dist = curr - zone.top
                if curr > zone.bottom and dist <= max_dist:
                    if best_buy is None or dist < best_buy["dist"]:
                        best_buy = {"zone": zone, "dist": max(0.0, dist)}

        # Konflik: pilih zona yang lebih dekat
        if best_buy and best_sell:
            if best_buy["dist"] <= best_sell["dist"]:
                best_sell = None
            else:
                best_buy = None

        if best_sell:
            z        = best_sell["zone"]
            entry    = z.mid
            sl_dist  = (z.top - entry) + buf
            tp_dist  = sl_dist * IFVG_RR
            gap_size = z.top - z.bottom

            if sl_dist <= 0:
                return StrategySignal(self.strategy_id, "HOLD", reason="sl_zero")

            confidence = min(0.75, max(0.40, 1.0 - z.bars_ago / IFVG_LOOKBACK))
            log.info(
                f"[{pair}] IFVG SELL | zone=[{z.bottom:.5f}~{z.top:.5f}]"
                f" entry={entry:.5f} | gap={gap_size:.5f} | age={z.bars_ago}bars"
            )
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="SELL",
                order_type="LIMIT",
                entry_price=round(entry, 5),
                sl_distance=round(sl_dist, 5),
                tp_distance=round(tp_dist, 5),
                reason=(
                    f"ifvg_bear|zone:[{z.bottom:.5f}~{z.top:.5f}]"
                    f"|gap:{gap_size:.5f}|age:{z.bars_ago}bars"
                ),
                confidence=confidence,
            )

        if best_buy:
            z        = best_buy["zone"]
            entry    = z.mid
            sl_dist  = (entry - z.bottom) + buf
            tp_dist  = sl_dist * IFVG_RR
            gap_size = z.top - z.bottom

            if sl_dist <= 0:
                return StrategySignal(self.strategy_id, "HOLD", reason="sl_zero")

            confidence = min(0.75, max(0.40, 1.0 - z.bars_ago / IFVG_LOOKBACK))
            log.info(
                f"[{pair}] IFVG BUY | zone=[{z.bottom:.5f}~{z.top:.5f}]"
                f" entry={entry:.5f} | gap={gap_size:.5f} | age={z.bars_ago}bars"
            )
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="BUY",
                order_type="LIMIT",
                entry_price=round(entry, 5),
                sl_distance=round(sl_dist, 5),
                tp_distance=round(tp_dist, 5),
                reason=(
                    f"ifvg_bull|zone:[{z.bottom:.5f}~{z.top:.5f}]"
                    f"|gap:{gap_size:.5f}|age:{z.bars_ago}bars"
                ),
                confidence=confidence,
            )

        return StrategySignal(
            self.strategy_id, "HOLD",
            reason=f"no_ifvg_zone|close:{curr:.5f}",
        )
