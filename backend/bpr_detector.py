"""
BPR (Balanced Price Range) detector.
Konsep dari ICT/SMC trading.

BPR terbentuk ketika Bullish FVG dan Bearish FVG saling tumpang tindih
di rentang harga yang sama. Area irisan (overlap) merepresentasikan zona
kesetimbangan institusional — price cenderung reject kuat saat retrace ke sana.

Perbedaan dari fvg_detector standard:
  1. Displacement filter: kandil tengah (C2) harus body-dominated (body/range >= ratio).
     Memastikan FVG terbentuk oleh impulse institusional, bukan noise.
  2. Mitigation 50%: FVG dianggap habis hanya jika price melewati midpoint zone,
     bukan sekadar menyentuh tepi (lebih akurat dengan definisi ICT).
  3. BPR freshness: dicek dari titik terbentuknya FVG yang lebih baru.
"""
from __future__ import annotations
import pandas as pd
from dataclasses import dataclass
from fvg_detector import FVGZone


@dataclass
class BPRZone:
    direction:      str      # "BUY" | "SELL" — ditentukan FVG yang lebih baru
    top:            float    # batas atas zona overlap
    bottom:         float    # batas bawah zona overlap
    mid:            float    # midpoint zona overlap
    bull_fvg:       FVGZone  # komponen Bullish FVG
    bear_fvg:       FVGZone  # komponen Bearish FVG
    newer_bars_ago: int      # usia FVG yang lebih baru (ukuran kesegaran BPR)
    older_bars_ago: int      # usia FVG yang lebih tua
    quality:        float    # skor kualitas (lebih besar = lebih baik)


def _detect_fvg_quality(
    df:                 pd.DataFrame,
    lookback:           int,
    min_gap:            float,
    displacement_ratio: float,
) -> list[FVGZone]:
    """
    Scan FVG dengan filter kualitas displacement candle (kandil C2).

    Berbeda dari detect_fvg() standar:
    - C2 harus memiliki body >= displacement_ratio × candle_range
    - Mitigated jika price melewati midpoint (50%), bukan sekadar menyentuh tepi
    """
    zones: list[FVGZone] = []
    end   = len(df) - 2
    start = max(2, end - lookback)

    for i in range(start, end + 1):
        c1 = df.iloc[i - 2]   # kandil 1 — sebelum impulse
        c2 = df.iloc[i - 1]   # kandil 2 — displacement (harus body-dominated)
        c3 = df.iloc[i]       # kandil 3 — setelah impulse

        # ── Filter displacement C2 ────────────────────────────────────────
        c2_range = c2["high"] - c2["low"]
        if c2_range <= 0:
            continue
        if abs(c2["close"] - c2["open"]) / c2_range < displacement_ratio:
            continue

        # ── Deteksi tipe FVG ──────────────────────────────────────────────
        gap_top = gap_bottom = 0.0
        direction = ""

        if c3["low"] > c1["high"]:           # Bullish FVG
            gap_bottom = c1["high"]
            gap_top    = c3["low"]
            direction  = "BUY"
        elif c3["high"] < c1["low"]:         # Bearish FVG
            gap_bottom = c3["high"]
            gap_top    = c1["low"]
            direction  = "SELL"

        if not direction or (gap_top - gap_bottom) < min_gap:
            continue

        mid = (gap_top + gap_bottom) / 2.0

        # ── Mitigasi di level 50% (bukan sekadar menyentuh tepi) ─────────
        subsequent = df.iloc[i + 1:]
        if direction == "BUY":
            mitigated = bool((subsequent["low"] <= mid).any())
        else:
            mitigated = bool((subsequent["high"] >= mid).any())

        bars_ago = len(df) - 1 - i

        zones.append(FVGZone(
            direction=direction,
            top=round(gap_top, 8),
            bottom=round(gap_bottom, 8),
            mid=round(mid, 8),
            fresh=not mitigated,
            bars_ago=bars_ago,
        ))

    zones.sort(key=lambda z: (not z.fresh, z.bars_ago))
    return zones


def detect_bpr(
    df:                 pd.DataFrame,
    lookback:           int   = 100,
    min_gap:            float = 0.0,
    displacement_ratio: float = 0.5,
    max_temporal_gap:   int   = 24,
) -> list[BPRZone]:
    """
    Deteksi semua zona BPR fresh — pasangan Bullish+Bearish FVG yang overlap.

    Return diurutkan dari kualitas tertinggi (overlap terbesar + paling baru).
    Hanya mengembalikan zona yang belum tersentuh (fresh) di midpoint.
    """
    all_fvgs = _detect_fvg_quality(df, lookback, min_gap, displacement_ratio)

    bull_fvgs = [z for z in all_fvgs if z.direction == "BUY"  and z.fresh]
    bear_fvgs = [z for z in all_fvgs if z.direction == "SELL" and z.fresh]

    bpr_zones: list[BPRZone] = []

    for bull in bull_fvgs:
        for bear in bear_fvgs:
            overlap_top    = min(bull.top,    bear.top)
            overlap_bottom = max(bull.bottom, bear.bottom)

            if overlap_top <= overlap_bottom:
                continue  # tidak ada irisan nyata

            overlap_mid  = (overlap_top + overlap_bottom) / 2.0
            overlap_size = overlap_top - overlap_bottom

            # ICT BPR = V-shape lokal — dua FVG harus terbentuk dalam rentang waktu dekat
            if abs(bull.bars_ago - bear.bars_ago) > max_temporal_gap:
                continue

            # Arah BPR ditentukan oleh FVG yang lebih baru
            if bull.bars_ago <= bear.bars_ago:
                direction      = "BUY"
                newer_bars_ago = bull.bars_ago
                older_bars_ago = bear.bars_ago
            else:
                direction      = "SELL"
                newer_bars_ago = bear.bars_ago
                older_bars_ago = bull.bars_ago

            # Freshness: cek apakah price sudah melewati midpoint BPR
            # dihitung dari candle setelah FVG yang lebih baru terbentuk
            start_idx  = max(0, len(df) - newer_bars_ago)
            subsequent = df.iloc[start_idx:]
            if direction == "BUY":
                still_fresh = not bool((subsequent["low"] <= overlap_mid).any())
            else:
                still_fresh = not bool((subsequent["high"] >= overlap_mid).any())

            if not still_fresh:
                continue

            # Kualitas: overlap besar + usia muda = skor tinggi
            quality = round(
                overlap_size
                - newer_bars_ago * 0.0001
                - older_bars_ago * 0.00005,
                8,
            )

            bpr_zones.append(BPRZone(
                direction=direction,
                top=round(overlap_top, 8),
                bottom=round(overlap_bottom, 8),
                mid=round(overlap_mid, 8),
                bull_fvg=bull,
                bear_fvg=bear,
                newer_bars_ago=newer_bars_ago,
                older_bars_ago=older_bars_ago,
                quality=quality,
            ))

    bpr_zones.sort(key=lambda z: -z.quality)
    return bpr_zones


def find_nearest_bpr(
    df:                 pd.DataFrame,
    direction:          str,
    proximity_atr:      float = 1.5,
    lookback:           int   = 100,
    min_gap_atr:        float = 0.3,
    displacement_ratio: float = 0.5,
    max_age_bars:       int   = 60,
    max_temporal_gap:   int   = 24,
) -> BPRZone | None:
    """
    Cari BPR fresh terdekat ke harga saat ini yang searah dengan direction.

    Price dianggap "mendekati" BPR jika:
    - Sudah berada di dalam zona (between bottom dan top), atau
    - Berjarak <= proximity_atr × ATR dari tepi zona (approaching)
    """
    if "atr" not in df.columns or pd.isna(df["atr"].iloc[-1]):
        return None

    atr      = df["atr"].iloc[-1]
    min_gap  = min_gap_atr * atr
    curr     = df["close"].iloc[-1]
    max_dist = proximity_atr * atr

    zones = detect_bpr(df, lookback=lookback, min_gap=min_gap,
                       displacement_ratio=displacement_ratio,
                       max_temporal_gap=max_temporal_gap)

    for z in zones:
        if z.direction != direction:
            continue
        if z.newer_bars_ago > max_age_bars:
            continue

        if direction == "BUY":
            # Price approaching BPR dari atas, atau sudah di dalam zona
            if curr >= z.bottom:
                dist = max(0.0, curr - z.top)   # 0 jika sudah di dalam zona
                if dist <= max_dist:
                    return z
        else:
            # Price approaching BPR dari bawah, atau sudah di dalam zona
            if curr <= z.top:
                dist = max(0.0, z.bottom - curr)
                if dist <= max_dist:
                    return z

    return None
