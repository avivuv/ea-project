"""
Risk check sebelum setiap order (RULES §5). Logika murni — mudah dites.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RiskState:
    spread_pips: float
    open_positions: list[tuple[str, float]] = field(default_factory=list)   # (direction, zero)
    trades_today: int = 0
    pnl_today_usd: float = 0.0
    paused: bool = False
    price_age_sec: float = 0.0


@dataclass
class RiskLimits:
    max_zone_distance: float
    max_spread_pips: float
    max_positions: int
    max_trades_day: int
    daily_loss_usd: float
    daily_profit_usd: float = 0.0           # target profit harian; 0 = nonaktif
    max_price_age_sec: float = 10.0


def target_hit(realized_usd: float, floating_usd: float, target_usd: float) -> bool:
    """Target profit harian tercapai (profit tertutup + mengambang). target 0 = nonaktif."""
    return target_usd > 0 and realized_usd + floating_usd >= target_usd


def check(direction: str, zone_zero: float, zone_distance: float,
          st: RiskState, lim: RiskLimits) -> tuple[bool, str]:
    """Return (boleh_order, alasan). Alasan kosong bila boleh."""
    if st.paused:
        return False, "PAUSED"
    if st.price_age_sec > lim.max_price_age_sec:
        return False, "PRICE_STALE"
    if zone_distance > lim.max_zone_distance:
        return False, "ZONE_TOO_FAR"
    if st.spread_pips > lim.max_spread_pips:
        return False, "SPREAD_TOO_WIDE"
    if st.pnl_today_usd <= -lim.daily_loss_usd:
        return False, "DAILY_LOSS_LIMIT"
    if lim.daily_profit_usd > 0 and st.pnl_today_usd >= lim.daily_profit_usd:
        return False, "DAILY_PROFIT_TARGET"
    if st.trades_today >= lim.max_trades_day:
        return False, "MAX_TRADES_DAY"
    if len(st.open_positions) >= lim.max_positions:
        return False, "MAX_POSITIONS"
    if any(d == direction and abs(z - zone_zero) < 0.01 for d, z in st.open_positions):
        return False, "DUPLICATE_OPEN"
    return True, ""
