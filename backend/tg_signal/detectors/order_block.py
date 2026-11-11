"""
CHoCH (Change of Character) detector + Order Block finder.
Diadopsi dari logika SnR 2.2.4 (Pending Order).
Digunakan oleh Strategy 4: StrategyCHoCHOB.
"""
from __future__ import annotations
import pandas as pd
from dataclasses import dataclass


@dataclass
class OrderBlock:
    direction: str   # "BUY" (demand zone) | "SELL" (supply zone)
    top:       float
    bottom:    float
    score:     float
    bars_ago:  int   # berapa candle lalu OB ini terbentuk


def _find_swing_points(df: pd.DataFrame, period: int) -> tuple[list, list]:
    """
    Return (swing_highs, swing_lows) sebagai list of (index, price).
    Swing high: high[i] adalah max dari i-period hingga i+period.
    Hanya scan sampai bar -2 (exclude bar pembentuk terkini yang belum konfirmasi).
    """
    highs, lows = [], []
    end = len(df) - 2  # exclude candle terakhir (belum konfirmasi)
    for i in range(period, end - period + 1):
        window_h = df["high"].iloc[i - period: i + period + 1]
        window_l = df["low"].iloc[i - period: i + period + 1]
        if df["high"].iloc[i] >= window_h.max():
            highs.append((i, df["high"].iloc[i]))
        if df["low"].iloc[i] <= window_l.min():
            lows.append((i, df["low"].iloc[i]))
    return highs, lows


def detect_choch(df: pd.DataFrame, period: int = 15) -> tuple[bool, bool]:
    """
    Deteksi CHoCH (Change of Character).

    Bullish CHoCH: struktur bearish (Lower High terakhir) tapi candle terkini
                   break di atas swing high sebelumnya → struktur berubah ke bullish.
    Bearish CHoCH: struktur bullish (Higher Low terakhir) tapi candle terkini
                   break di bawah swing low sebelumnya → struktur berubah ke bearish.

    Return (bullish_choch, bearish_choch).
    """
    if len(df) < period * 4:
        return False, False

    highs, lows = _find_swing_points(df, period)

    if len(highs) < 2 or len(lows) < 2:
        return False, False

    curr_high = df["high"].iloc[-1]
    curr_low  = df["low"].iloc[-1]
    last_idx  = len(df) - 1

    # Swing points terakhir
    sh1_idx, sh1 = highs[-1]
    sh2_idx, sh2 = highs[-2]
    sl1_idx, sl1 = lows[-1]
    sl2_idx, sl2 = lows[-2]

    # Jarak maksimum: swing harus cukup baru (< 4× period bars)
    max_gap = period * 4

    bullish_choch = (
        sh1 < sh2                       # Lower High → downtrend / bearish structure
        and curr_high > sh1             # break di atas swing high terakhir
        and (last_idx - sh1_idx) <= max_gap
    )
    bearish_choch = (
        sl1 > sl2                       # Higher Low → uptrend / bullish structure
        and curr_low < sl1              # break di bawah swing low terakhir
        and (last_idx - sl1_idx) <= max_gap
    )

    return bullish_choch, bearish_choch


def find_best_order_block(
    df: pd.DataFrame,
    direction: str,
    lookback: int = 30,
    body_min_ratio: float = 0.6,
) -> OrderBlock | None:
    """
    Cari Order Block terbaik untuk direction yang diberikan.

    BUY  → cari candle bearish dengan body besar (demand zone sebelum impulse naik)
    SELL → cari candle bullish dengan body besar (supply zone sebelum impulse turun)

    Score = body_ratio × 10 − (bars_ago / lookback) × 3
    (body besar + lebih baru = skor lebih tinggi)
    """
    if len(df) < lookback + 5:
        return None

    # Scan lookback bars, exclude candle terakhir (sedang terbentuk)
    scan_start = max(0, len(df) - lookback - 1)
    scan_df = df.iloc[scan_start: len(df) - 1]

    best: OrderBlock | None = None
    best_score = -999.0

    for i in range(len(scan_df)):
        row = scan_df.iloc[i]
        candle_range = row["high"] - row["low"]
        if candle_range <= 0:
            continue

        body       = abs(row["close"] - row["open"])
        body_ratio = body / candle_range

        if body_ratio < body_min_ratio:
            continue

        is_bearish = row["close"] < row["open"]
        is_bullish = row["close"] > row["open"]

        if direction == "BUY"  and not is_bearish:
            continue
        if direction == "SELL" and not is_bullish:
            continue

        bars_ago = len(scan_df) - i
        score    = body_ratio * 10 - (bars_ago / max(lookback, 1)) * 3

        if score > best_score:
            best_score = score
            best = OrderBlock(
                direction=direction,
                top=round(row["high"], 8),
                bottom=round(row["low"], 8),
                score=round(score, 3),
                bars_ago=bars_ago,
            )

    return best
