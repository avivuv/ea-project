"""
Konfirmasi entry di dalam zona sinyal (RULES §3). Logika murni, dievaluasi pada bar yang SUDAH close.

Definisi (pola 3 candle c1, c2, c3 dengan c3 = bar yang baru close):
- FVG   BUY : c3.low  > c1.high  (gap bullish, sama dengan detectors/fvg.py)
        SELL: c3.high < c1.low
- OB    BUY : c2 bearish (close < open) lalu c3 bullish dan close di atas c2.high
        SELL: c2 bullish lalu c3 bearish dan close di bawah c2.low
- OBIM  BUY : FVG bullish dengan c1 bearish (c1 = order block, c2 = impuls/imbalance)
        SELL: FVG bearish dengan c1 bullish

- REJ   BUY : 1 candle rejection — bar k bullish (close > open), sumbu bawah ≥ 50% range,
              low menyentuh zona
        SELL: bar k bearish, sumbu atas ≥ 50% range, high menyentuh zona

Syarat lokasi: pola harus "berasal" dari zona — low terendah (BUY) / high tertinggi (SELL)
dari ketiga candle menyentuh zona: ≤ zero + tol (BUY) atau ≥ zero − tol (SELL).
"""
from __future__ import annotations

from typing import Sequence

MODES = ("FVG", "OB", "OBIM", "REJ")
REJ_WICK_RATIO = 0.5


def confirmed(mode: str, direction: str, o: Sequence[float], h: Sequence[float],
              l: Sequence[float], c: Sequence[float], k: int, zero: float, tol: float = 0.5) -> bool:
    """True bila bar ke-k (sudah close) memberi konfirmasi `mode` searah `direction`."""
    if mode == "REJ":
        rng = h[k] - l[k]
        if k < 0 or rng <= 0:
            return False
        if direction == "BUY":
            return (l[k] <= zero + tol and c[k] > o[k]
                    and (min(o[k], c[k]) - l[k]) >= REJ_WICK_RATIO * rng)
        return (h[k] >= zero - tol and c[k] < o[k]
                and (h[k] - max(o[k], c[k])) >= REJ_WICK_RATIO * rng)
    if k < 2:
        return False
    i1, i2, i3 = k - 2, k - 1, k
    if direction == "BUY":
        if min(l[i1], l[i2], l[i3]) > zero + tol:
            return False
        if mode == "FVG":
            return l[i3] > h[i1]
        if mode == "OB":
            return c[i2] < o[i2] and c[i3] > o[i3] and c[i3] > h[i2]
        if mode == "OBIM":
            return l[i3] > h[i1] and c[i1] < o[i1]
    else:
        if max(h[i1], h[i2], h[i3]) < zero - tol:
            return False
        if mode == "FVG":
            return h[i3] < l[i1]
        if mode == "OB":
            return c[i2] > o[i2] and c[i3] < o[i3] and c[i3] < l[i2]
        if mode == "OBIM":
            return h[i3] < l[i1] and c[i1] > o[i1]
    raise ValueError(f"mode tidak dikenal: {mode}")
