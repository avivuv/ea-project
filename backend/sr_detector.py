"""
Support/Resistance level detector — berbasis swing high/low.
Dipakai sebagai confidence bonus di strategy runner, bukan hard filter.
"""
from __future__ import annotations
import pandas as pd


def find_sr_levels(df: pd.DataFrame, lookback: int = 80, swing_period: int = 5) -> list[float]:
    """
    Deteksi S/R levels dari swing high/low dalam N candle terakhir.
    Swing high: candle high tertinggi dibanding swing_period candle di kiri dan kanan.
    Swing low : candle low terendah dibanding swing_period candle di kiri dan kanan.
    """
    if len(df) < swing_period * 2 + 5:
        return []

    recent = df.iloc[-lookback:].reset_index(drop=True)
    levels: list[float] = []
    n = len(recent)

    for i in range(swing_period, n - swing_period):
        high_i = recent["high"].iloc[i]
        low_i  = recent["low"].iloc[i]

        left_highs  = recent["high"].iloc[i - swing_period : i]
        right_highs = recent["high"].iloc[i + 1 : i + swing_period + 1]
        left_lows   = recent["low"].iloc[i - swing_period : i]
        right_lows  = recent["low"].iloc[i + 1 : i + swing_period + 1]

        if (left_highs <= high_i).all() and (right_highs <= high_i).all():
            levels.append(high_i)

        if (left_lows >= low_i).all() and (right_lows >= low_i).all():
            levels.append(low_i)

    return levels


def near_sr_level(price: float, levels: list[float], atr: float, tolerance: float = 0.5) -> bool:
    """Return True jika price berada dalam tolerance × ATR dari S/R level manapun."""
    if not levels or atr <= 0:
        return False
    return any(abs(price - lvl) <= tolerance * atr for lvl in levels)
