from __future__ import annotations
import pandas as pd
import ta
from config import (
    ATR_PERIOD,
    SD_PROXIMITY_ATR, SD_ZONE_BUFFER_ATR,
    SD_TP_ATR_MULT, SL_ATR_MULTIPLIER, SD_H4_EMA_CONFIRM,
    SD_H4_EMA_FAST, SD_H4_EMA_SLOW,
    SD_PENDING_EXPIRY_CANDLES,
)
from supply_demand import detect_zones, find_nearest_zone, price_in_zone
from .base import BaseStrategy, StrategySignal, HOLD_SIGNAL


class StrategySND(BaseStrategy):
    """
    Strategy 2 — Supply & Demand Zone.
    Entry berupa:
    - LIMIT order saat harga mendekati zone (belum di dalam)
    - MARKET order saat harga sudah berada di dalam zone
    Data H4 digunakan untuk deteksi zone, H1 untuk konfirmasi trend.
    """
    strategy_id = "SND"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,   # H1 — trend konfirmasi
        h4_ohlcv:  list | None = None,   # H4 — zone detection
    ) -> StrategySignal:

        if not h4_ohlcv or len(h4_ohlcv) < 50:
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="HOLD",
                reason="snd:no_h4_data",
            )

        # ── Harga saat ini dari M15 ───────────────────────────────────────────
        current_price = float(ohlcv[-1]["close"])

        # ── ATR dari H4 untuk referensi zone proximity ────────────────────────
        h4_df = pd.DataFrame(h4_ohlcv)
        h4_df.columns = [c.lower() for c in h4_df.columns]
        atr_series = ta.volatility.average_true_range(
            h4_df["high"], h4_df["low"], h4_df["close"], window=ATR_PERIOD
        )
        h4_atr = float(atr_series.iloc[-1])
        if pd.isna(h4_atr) or h4_atr <= 0:
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="HOLD",
                reason="snd:h4_atr_invalid",
            )

        # ── Trend dari H4 EMA ─────────────────────────────────────────────────
        h4_ema_fast = ta.trend.ema_indicator(h4_df["close"], window=SD_H4_EMA_FAST).iloc[-1]
        h4_ema_slow = ta.trend.ema_indicator(h4_df["close"], window=SD_H4_EMA_SLOW).iloc[-1]
        if pd.isna(h4_ema_fast) or pd.isna(h4_ema_slow):
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="HOLD",
                reason="snd:h4_ema_invalid",
            )

        h4_bullish = h4_ema_fast > h4_ema_slow
        h4_bearish = h4_ema_fast < h4_ema_slow

        # ── Deteksi S&D zones dari H4 ─────────────────────────────────────────
        zones = detect_zones(h4_ohlcv)
        if not zones:
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="HOLD",
                reason="snd:no_zones_detected",
            )

        proximity = SD_PROXIMITY_ATR * h4_atr
        sl_dist   = h4_atr * SL_ATR_MULTIPLIER
        tp_dist   = h4_atr * SD_TP_ATR_MULT

        # ── Cek SELL setup: supply zone + bearish trend ───────────────────────
        if h4_bearish or not SD_H4_EMA_CONFIRM:
            supply = find_nearest_zone(zones, "SUPPLY", current_price)
            if supply:
                in_zone       = price_in_zone(current_price, supply, buffer=h4_atr * 0.1)
                near_zone     = current_price >= (supply.bottom - proximity)
                zone_freshness = "fresh" if supply.fresh else "tested"

                if in_zone:
                    # Harga sudah di dalam supply zone → market order SELL
                    sl_price_ref = supply.top + h4_atr * SD_ZONE_BUFFER_ATR
                    return StrategySignal(
                        strategy_id=self.strategy_id,
                        direction="SELL",
                        order_type="MARKET",
                        entry_price=0.0,
                        sl_distance=abs(sl_price_ref - current_price),
                        tp_distance=tp_dist,
                        reason=f"snd:sell_in_supply|zone={supply.bottom:.5f}-{supply.top:.5f}|{zone_freshness}|str={supply.strength:.2f}",
                        confidence=round(min(0.90, supply.strength * (0.90 if supply.fresh else 0.70)), 2),
                    )

                if near_zone:
                    # Harga mendekati supply zone → pending SELL LIMIT di lower edge
                    entry   = round(supply.bottom, 5)
                    sl_dist_limit = abs((supply.top + h4_atr * SD_ZONE_BUFFER_ATR) - entry)
                    return StrategySignal(
                        strategy_id=self.strategy_id,
                        direction="SELL",
                        order_type="LIMIT",
                        entry_price=entry,
                        sl_distance=sl_dist_limit,
                        tp_distance=tp_dist,
                        reason=f"snd:sell_limit_supply|entry={entry}|zone={supply.bottom:.5f}-{supply.top:.5f}|{zone_freshness}|str={supply.strength:.2f}|expiry={SD_PENDING_EXPIRY_CANDLES}c",
                        confidence=round(min(0.87, supply.strength * (0.87 if supply.fresh else 0.68)), 2),
                    )

        # ── Cek BUY setup: demand zone + bullish trend ────────────────────────
        if h4_bullish or not SD_H4_EMA_CONFIRM:
            demand = find_nearest_zone(zones, "DEMAND", current_price)
            if demand:
                in_zone       = price_in_zone(current_price, demand, buffer=h4_atr * 0.1)
                near_zone     = current_price <= (demand.top + proximity)
                zone_freshness = "fresh" if demand.fresh else "tested"

                if in_zone:
                    sl_price_ref = demand.bottom - h4_atr * SD_ZONE_BUFFER_ATR
                    return StrategySignal(
                        strategy_id=self.strategy_id,
                        direction="BUY",
                        order_type="MARKET",
                        entry_price=0.0,
                        sl_distance=abs(current_price - sl_price_ref),
                        tp_distance=tp_dist,
                        reason=f"snd:buy_in_demand|zone={demand.bottom:.5f}-{demand.top:.5f}|{zone_freshness}|str={demand.strength:.2f}",
                        confidence=round(min(0.90, demand.strength * (0.90 if demand.fresh else 0.70)), 2),
                    )

                if near_zone:
                    entry   = round(demand.top, 5)
                    sl_dist_limit = abs(entry - (demand.bottom - h4_atr * SD_ZONE_BUFFER_ATR))
                    return StrategySignal(
                        strategy_id=self.strategy_id,
                        direction="BUY",
                        order_type="LIMIT",
                        entry_price=entry,
                        sl_distance=sl_dist_limit,
                        tp_distance=tp_dist,
                        reason=f"snd:buy_limit_demand|entry={entry}|zone={demand.bottom:.5f}-{demand.top:.5f}|{zone_freshness}|str={demand.strength:.2f}|expiry={SD_PENDING_EXPIRY_CANDLES}c",
                        confidence=round(min(0.87, demand.strength * (0.87 if demand.fresh else 0.68)), 2),
                    )

        return StrategySignal(
            strategy_id=self.strategy_id,
            direction="HOLD",
            reason=f"snd:no_setup|h4={'bull' if h4_bullish else 'bear'}|zones={len(zones)}",
        )
