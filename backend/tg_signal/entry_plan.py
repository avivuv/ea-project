"""
Rencana entry mengikuti zona sinyal (TG_ENTRY_MODE=ZONE). Logika murni, tanpa MT5.

- Harga sudah di zona (BUY: ask ≤ ZERO, SELL: bid ≥ ZERO) → entry market sekarang.
- Belum sampai zona → pending limit di ZERO (BUY LIMIT / SELL LIMIT).
- SL = LAST ∓ sl_pips (mengikuti zona sinyal), TP = entry ± tp_pips.
- Harga sudah melewati level SL → tolak (sinyal sudah gagal).
- Pending batal bila harga sudah sampai ZERO ± tp_pips ke arah TP tanpa ter-fill
  (sinyal sudah selesai TP tanpa kita).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntryPlan:
    kind: str            # MARKET | LIMIT | REJECT
    price: float = 0.0   # MARKET: perkiraan harga isi · LIMIT: harga limit
    sl: float = 0.0
    tp: float = 0.0
    reason: str = ""


def plan_entry(direction: str, zero: float, last: float, bid: float, ask: float,
               sl_dist: float, tp_dist: float) -> EntryPlan:
    """Jarak sl_dist/tp_dist dalam satuan harga."""
    g = 1 if direction == "BUY" else -1
    sl = last - g * sl_dist
    fill_px = ask if g == 1 else bid          # harga isi bila masuk market
    exit_px = bid if g == 1 else ask          # harga yang memicu SL
    if g * (exit_px - sl) <= 0:
        return EntryPlan("REJECT", reason="PAST_SL")
    if g * (fill_px - zero) <= 0:             # sudah di dalam (atau melewati) ZERO
        return EntryPlan("MARKET", fill_px, sl, fill_px + g * tp_dist)
    return EntryPlan("LIMIT", zero, sl, zero + g * tp_dist)


def limit_filled(direction: str, limit: float, bid: float, ask: float) -> bool:
    """Simulasi paper: BUY LIMIT terisi saat ask ≤ limit, SELL LIMIT saat bid ≥ limit."""
    return ask <= limit if direction == "BUY" else bid >= limit


def pending_expired(direction: str, zero: float, bid: float, ask: float, tp_dist: float) -> bool:
    """Harga sudah bergerak ZERO ± TP ke arah TP tanpa mengisi limit → sinyal selesai, batalkan."""
    if direction == "BUY":
        return bid >= zero + tp_dist
    return ask <= zero - tp_dist
