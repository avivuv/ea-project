"""
Konversi 2 digit sinyal → harga penuh XAUUSD (SIGNAL_SPEC §2, §3).

Logika murni: tidak boleh import MetaTrader5 / telethon.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


def resolve_level(n: int, ref: float) -> float:
    """2 digit terakhir bagian bulat → kandidat harga terdekat dari `ref`.
    Level ≥ 1000 dianggap sudah harga penuh."""
    if n >= 1000:
        return float(n)
    if not 0 <= n <= 99:
        raise ValueError(f"level harus 0-99 atau harga penuh ≥1000, dapat {n}")
    base = math.floor(ref / 100) * 100
    candidates = (base - 100 + n, base + n, base + 100 + n)
    return float(min(candidates, key=lambda c: abs(c - ref)))


@dataclass
class Zone:
    direction: str          # BUY | SELL
    zero: float             # tepi yang disentuh lebih dulu (angka pertama)
    last: float             # ujung terdalam (angka kedua)
    ref_price: float
    flags: list[str] = field(default_factory=list)

    @property
    def mid(self) -> float:
        return (self.zero + self.last) / 2

    @property
    def top(self) -> float:
        return max(self.zero, self.last)

    @property
    def bottom(self) -> float:
        return min(self.zero, self.last)

    @property
    def width(self) -> float:
        return self.top - self.bottom

    @property
    def distance(self) -> float:
        """Jarak harga referensi ke zona (0 bila sudah di dalam zona)."""
        if self.bottom <= self.ref_price <= self.top:
            return 0.0
        return min(abs(self.ref_price - self.top), abs(self.ref_price - self.bottom))


def resolve_zone(
    direction: str,
    level_first: int,
    level_last: int,
    ref: float,
    width_min: float = 1,
    width_max: float = 10,
) -> Zone:
    """Resolve kedua angka secara terpisah lalu beri flag bila mencurigakan."""
    direction = direction.upper()
    zone = Zone(
        direction=direction,
        zero=resolve_level(level_first, ref),
        last=resolve_level(level_last, ref),
        ref_price=ref,
    )
    if direction == "BUY" and not zone.zero > zone.last:
        zone.flags.append("ZONE_ORDER_SUSPECT")
    if direction == "SELL" and not zone.zero < zone.last:
        zone.flags.append("ZONE_ORDER_SUSPECT")
    if not width_min <= zone.width <= width_max:
        zone.flags.append("ZONE_WIDTH_SUSPECT")
    return zone
