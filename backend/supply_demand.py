from __future__ import annotations
import pandas as pd
import ta
from dataclasses import dataclass
from typing import Literal
from config import (
    SD_IMPULSE_ATR_MULT, SD_BASE_ATR_MULT, SD_BASE_CANDLES,
    SD_LOOKBACK, SD_MIN_STRENGTH, ATR_PERIOD,
)


@dataclass
class SDZone:
    type:       Literal["SUPPLY", "DEMAND"]
    top:        float
    bottom:     float
    fresh:      bool    # belum pernah disentuh harga sejak terbentuk
    strength:   float   # 0–1, berdasarkan ukuran impulse candle
    formed_ago: int     # berapa candle lalu zone ini terbentuk


def detect_zones(ohlcv: list, lookback: int | None = None) -> list[SDZone]:
    """
    Deteksi Supply & Demand zone dari data OHLCV (biasanya H4).

    Algoritma Rally-Base-Drop (Supply) dan Drop-Base-Rally (Demand):
    1. Cari impulse candle besar (body >= SD_IMPULSE_ATR_MULT × ATR)
    2. Cek 1–SD_BASE_CANDLES candle sebelumnya sebagai "base" (body kecil)
    3. Zone = range high/low dari candle base
    4. Fresh = harga belum kembali ke zone sejak terbentuk
    """
    if not ohlcv or len(ohlcv) < ATR_PERIOD + SD_BASE_CANDLES + 5:
        return []

    df = pd.DataFrame(ohlcv)
    df.columns = [c.lower() for c in df.columns]
    df["atr"] = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=ATR_PERIOD
    )

    max_lookback = lookback or SD_LOOKBACK
    scan_start   = max(ATR_PERIOD + SD_BASE_CANDLES + 1, len(df) - max_lookback)

    zones: list[SDZone] = []

    for i in range(scan_start, len(df) - 1):
        candle = df.iloc[i]
        atr    = candle["atr"]
        if pd.isna(atr) or atr <= 0:
            continue

        body = abs(candle["close"] - candle["open"])

        # ── Cari impulse candle ───────────────────────────────────────────────
        is_bearish_impulse = (
            candle["close"] < candle["open"]
            and body >= SD_IMPULSE_ATR_MULT * atr
        )
        is_bullish_impulse = (
            candle["close"] > candle["open"]
            and body >= SD_IMPULSE_ATR_MULT * atr
        )

        if not (is_bearish_impulse or is_bullish_impulse):
            continue

        # ── Cari base candle sebelum impulse ─────────────────────────────────
        base_end   = i
        base_start = max(0, i - SD_BASE_CANDLES)
        base_df    = df.iloc[base_start:base_end]

        if len(base_df) == 0:
            continue

        base_bodies = (base_df["close"] - base_df["open"]).abs()
        if not (base_bodies < SD_BASE_ATR_MULT * atr).all():
            continue

        zone_top    = float(base_df["high"].max())
        zone_bottom = float(base_df["low"].min())

        if zone_top <= zone_bottom:
            continue

        # ── Cek freshness: harga belum masuk ke zone setelah terbentuk ───────
        future      = df.iloc[i + 1:]
        price_in    = ((future["low"] <= zone_top) & (future["high"] >= zone_bottom)).any()
        fresh       = not bool(price_in)

        strength    = min(1.0, body / (SD_IMPULSE_ATR_MULT * atr))
        if strength < SD_MIN_STRENGTH:
            continue

        formed_ago  = len(df) - 1 - i

        zone_type: Literal["SUPPLY", "DEMAND"] = (
            "SUPPLY" if is_bearish_impulse else "DEMAND"
        )
        zones.append(SDZone(
            type=zone_type,
            top=zone_top,
            bottom=zone_bottom,
            fresh=fresh,
            strength=strength,
            formed_ago=formed_ago,
        ))

    # Urutkan: fresh dulu, kemudian kekuatan
    zones.sort(key=lambda z: (-int(z.fresh), -z.strength))
    return zones


def find_nearest_zone(
    zones:     list[SDZone],
    zone_type: Literal["SUPPLY", "DEMAND"],
    current_price: float,
) -> SDZone | None:
    """Kembalikan zone terdekat di atas (SUPPLY) atau di bawah (DEMAND) harga saat ini."""
    candidates = [z for z in zones if z.type == zone_type]
    if not candidates:
        return None

    if zone_type == "SUPPLY":
        # Supply zone harus di ATAS harga saat ini
        above = [z for z in candidates if z.bottom > current_price]
        if not above:
            return None
        return min(above, key=lambda z: z.bottom)
    else:
        # Demand zone harus di BAWAH harga saat ini
        below = [z for z in candidates if z.top < current_price]
        if not below:
            return None
        return max(below, key=lambda z: z.top)


def price_in_zone(price: float, zone: SDZone, buffer: float = 0.0) -> bool:
    return (zone.bottom - buffer) <= price <= (zone.top + buffer)
