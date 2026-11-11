"""
Fair Value Gap (FVG) detector.
Konsep dari ICT/SMC trading.

FVG terbentuk dari 3 candle berurutan ketika candle tengah bergerak
sangat kuat sehingga ada "gap" antara candle sebelum dan sesudahnya.

Bullish FVG: bar[i-2].high < bar[i].low  → gap di atas, zona demand
Bearish FVG: bar[i-2].low  > bar[i].high → gap di bawah, zona supply

Price sering kembali mengisi gap sebelum melanjutkan arah asal.
Entry: LIMIT saat price pull-back ke zona FVG.
"""
from __future__ import annotations
import pandas as pd
from dataclasses import dataclass


@dataclass
class FVGZone:
    direction: str   # "BUY" (bullish FVG) | "SELL" (bearish FVG)
    top:       float  # batas atas gap
    bottom:    float  # batas bawah gap
    mid:       float  # tengah gap (untuk entry)
    fresh:     bool   # True = price belum pernah masuk gap (unmitigated)
    bars_ago:  int    # berapa bar lalu FVG terbentuk


def detect_fvg(
    df:       pd.DataFrame,
    lookback: int   = 60,
    min_gap:  float = 0.0,   # minimum gap size (dalam satuan harga)
) -> list[FVGZone]:
    """
    Scan lookback candles terakhir, return semua FVG yang masih fresh.
    Diurutkan dari yang paling baru (bars_ago kecil) ke paling lama.
    """
    if len(df) < 5:
        return []

    zones: list[FVGZone] = []
    # Scan dari candle ke-2 terbaru ke belakang (exclude candle terakhir yg sedang terbentuk)
    end   = len(df) - 2
    start = max(2, end - lookback)

    for i in range(start, end + 1):
        c1 = df.iloc[i - 2]   # candle pertama (tertua dari tiga)
        c3 = df.iloc[i]       # candle ketiga (paling baru dari tiga)

        gap_top    = 0.0
        gap_bottom = 0.0
        direction  = ""

        # ── Bullish FVG ──────────────────────────────────────────────────
        if c3["low"] > c1["high"]:
            gap_bottom = c1["high"]
            gap_top    = c3["low"]
            direction  = "BUY"

        # ── Bearish FVG ──────────────────────────────────────────────────
        elif c3["high"] < c1["low"]:
            gap_bottom = c3["high"]
            gap_top    = c1["low"]
            direction  = "SELL"

        if not direction:
            continue

        gap_size = gap_top - gap_bottom
        if gap_size < min_gap:
            continue

        # Cek apakah FVG sudah "terisi" (mitigated) oleh candle setelahnya
        subsequent = df.iloc[i + 1:]
        if direction == "BUY":
            # Mitigated jika price pernah turun ke bawah gap_top (masuk zona)
            mitigated = bool((subsequent["low"] <= gap_top).any())
        else:
            # Mitigated jika price pernah naik di atas gap_bottom
            mitigated = bool((subsequent["high"] >= gap_bottom).any())

        bars_ago = len(df) - 1 - i

        zones.append(FVGZone(
            direction=direction,
            top=round(gap_top, 8),
            bottom=round(gap_bottom, 8),
            mid=round((gap_top + gap_bottom) / 2, 8),
            fresh=not mitigated,
            bars_ago=bars_ago,
        ))

    # Urutkan: fresh dulu, lalu bars_ago ascending (paling baru)
    zones.sort(key=lambda z: (not z.fresh, z.bars_ago))
    return zones


def find_nearest_fvg(
    df:            pd.DataFrame,
    direction:     str,
    proximity_atr: float = 2.0,
    lookback:      int   = 60,
    min_gap_atr:   float = 0.3,
) -> FVGZone | None:
    """
    Cari FVG fresh terdekat ke harga saat ini yang searah dengan direction.
    Hanya return jika price sudah cukup dekat (dalam proximity_atr × ATR).
    """
    if "atr" not in df.columns or pd.isna(df["atr"].iloc[-1]):
        return None

    atr       = df["atr"].iloc[-1]
    min_gap   = min_gap_atr * atr
    curr      = df["close"].iloc[-1]
    max_dist  = proximity_atr * atr

    zones = detect_fvg(df, lookback=lookback, min_gap=min_gap)

    for z in zones:
        if z.direction != direction or not z.fresh:
            continue

        # Jarak dari harga sekarang ke zona FVG
        if direction == "BUY":
            # Price harus di atas atau dekat dengan top gap (approaching from above)
            dist = curr - z.top
        else:
            # Price harus di bawah atau dekat dengan bottom gap
            dist = z.bottom - curr

        if 0 <= dist <= max_dist:
            return z

    return None
