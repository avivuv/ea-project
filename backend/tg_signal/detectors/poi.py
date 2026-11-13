"""
POI (point of interest) M1 untuk memilih area entry di dalam zona sinyal. Logika murni.

Semua fungsi bekerja di "ruang BUY" (zona demand). Untuk SELL panggil dengan harga dinegasikan:
o, h, l, c → -o, -l, -h, -c (sama seperti backtest_tg._space).

Jenis zona:
- FVG  : FVG bullish, c3.low > c1.high → [c1.high, c3.low]
- OB   : candle bearish terakhir (maks 3 bar) sebelum displacement yang membentuk FVG bullish
         → [low, open] candle itu
- IFVG : FVG bearish [c3.high, c1.low] yang kemudian ditembus close di atas c1.low
         → berbalik jadi support, aktif sejak bar penembusan

Zona boleh dipakai mulai bar `created + 1` (bar `created` sudah close) sampai bar `dead`
(bar yang close di bawah `bottom` → zona gagal / jadi IFVG berlawanan).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MAX_SCAN = 600          # batas pencarian invalidasi / inversi (bar)


@dataclass(frozen=True)
class POI:
    kind: str           # FVG | OB | IFVG
    top: float          # tepi proximal (disentuh lebih dulu saat harga turun)
    bottom: float       # tepi distal
    created: int        # indeks bar (sudah close) tempat zona terbentuk
    dead: int           # indeks bar yang close di bawah bottom (atau batas scan)


def _first(mask_slice: np.ndarray, start: int, default: int) -> int:
    idx = np.flatnonzero(mask_slice)
    return start + int(idx[0]) if len(idx) else default


def _dead_after(c: np.ndarray, start: int, bottom: float) -> int:
    end = min(len(c), start + MAX_SCAN)
    return _first(c[start:end] < bottom, start, end)


def find_pois(o, h, l, c, min_size: float = 0.2) -> list[POI]:
    """Semua POI demand di seluruh array, urut menurut `created`."""
    o, h, l, c = (np.asarray(x, float) for x in (o, h, l, c))
    n = len(c)
    out: list[POI] = []
    for i in range(2, n):
        # FVG bullish (+ OB asalnya)
        if l[i] - h[i - 2] >= min_size:
            bottom, top = h[i - 2], l[i]
            out.append(POI("FVG", top, bottom, i, _dead_after(c, i + 1, bottom)))
            for j in (i - 2, i - 3, i - 4):
                if j >= 0 and c[j] < o[j]:
                    if o[j] - l[j] >= min_size:
                        out.append(POI("OB", o[j], l[j], i, _dead_after(c, i + 1, l[j])))
                    break
        # FVG bearish → IFVG bila nanti ditembus close di atasnya
        if l[i - 2] - h[i] >= min_size:
            bottom, top = h[i], l[i - 2]
            end = min(n, i + 1 + MAX_SCAN)
            k = _first(c[i + 1:end] > top, i + 1, -1)
            if k >= 0:
                out.append(POI("IFVG", top, bottom, k, _dead_after(c, k + 1, bottom)))
    out.sort(key=lambda p: p.created)
    return out


def active_pois(pois: list[POI], j: int, lo: float, hi: float, max_age: int = 240) -> list[POI]:
    """POI yang bisa dipakai di bar j, beririsan dengan [lo, hi], umur ≤ max_age bar."""
    return [p for p in pois
            if p.created < j <= p.dead and j - p.created <= max_age
            and p.top >= lo and p.bottom <= hi]


def zone_pois(direction: str, o, h, l, c, zero: float, last: float, tol: float = 0.5,
              max_age: int = 240, min_size: float = 0.2) -> list[tuple[float, float, str]]:
    """POI searah sinyal yang masih aktif setelah bar terakhir (semua bar harus sudah close) dan tepi
    proximal-nya berada di zona [LAST, ZERO] ± tol. Harga asli, bukan ruang BUY.

    Return list (proximal, distal, jenis). BUY: proximal = tepi atas zona demand.
    SELL: proximal = tepi bawah zona supply.
    """
    o, h, l, c = (np.asarray(x, float) for x in (o, h, l, c))
    sgn = 1 if direction == "BUY" else -1
    arr = (o, h, l, c) if sgn == 1 else (-o, -l, -h, -c)
    z, la = sgn * zero, sgn * last
    lo, hi = la - tol, z + tol
    n = len(c)
    act = active_pois(find_pois(*arr, min_size=min_size), n, lo, hi, max_age)
    return [(sgn * p.top, sgn * p.bottom, p.kind) for p in act if lo <= p.top <= hi]
