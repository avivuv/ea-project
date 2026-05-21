from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

SignalDirection = Literal["BUY", "SELL", "HOLD"]
OrderType       = Literal["MARKET", "LIMIT", "STOP"]


@dataclass
class StrategySignal:
    strategy_id:  str
    direction:    SignalDirection
    order_type:   OrderType  = "MARKET"
    entry_price:  float      = 0.0   # 0 = gunakan harga pasar saat eksekusi
    sl_distance:  float      = 0.0
    tp_distance:  float      = 0.0
    reason:       str        = ""
    confidence:   float      = 0.0   # 0–1, dipakai runner untuk prioritas

    @property
    def is_active(self) -> bool:
        return self.direction != "HOLD"


HOLD_SIGNAL = StrategySignal(
    strategy_id="none",
    direction="HOLD",
    reason="no_signal",
)


class BaseStrategy:
    strategy_id: str = "base"

    def compute(
        self,
        ohlcv:      list,
        pair:       str,
        htf_ohlcv:  list | None = None,
        h4_ohlcv:   list | None = None,
    ) -> StrategySignal:
        raise NotImplementedError
