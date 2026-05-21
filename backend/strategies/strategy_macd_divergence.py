"""
Strategy 7 — MACD Divergence.

Bearish divergence: harga buat Higher High, MACD histogram buat Lower High → SELL
Bullish divergence: harga buat Lower Low,  MACD histogram buat Higher Low → BUY

Lebih reliable dari RSI divergence karena MACD mencakup trend + momentum.
Entry: MARKET setelah divergence terkonfirmasi pada candle close.
"""
from __future__ import annotations
import logging
import pandas as pd
import ta
from .base import BaseStrategy, StrategySignal
from config import (
    ATR_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    MACD_DIV_LOOKBACK, MACD_SL_ATR_MULT, MACD_RR,
)

log = logging.getLogger(__name__)


def _find_peaks(series: pd.Series, lookback: int) -> list[int]:
    """Return indeks local maxima dalam window lookback terakhir."""
    peaks = []
    data  = series.iloc[-lookback:]
    for i in range(1, len(data) - 1):
        if data.iloc[i] > data.iloc[i - 1] and data.iloc[i] > data.iloc[i + 1]:
            peaks.append(len(series) - lookback + i)
    return peaks


def _find_troughs(series: pd.Series, lookback: int) -> list[int]:
    """Return indeks local minima dalam window lookback terakhir."""
    troughs = []
    data    = series.iloc[-lookback:]
    for i in range(1, len(data) - 1):
        if data.iloc[i] < data.iloc[i - 1] and data.iloc[i] < data.iloc[i + 1]:
            troughs.append(len(series) - lookback + i)
    return troughs


class StrategyMACDDivergence(BaseStrategy):
    """
    Strategy 7 — MACD Divergence.
    Mendeteksi perbedaan arah antara price action dan momentum MACD.
    """
    strategy_id = "MACD_DIV"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:
        df = pd.DataFrame(ohlcv)
        df.columns = [c.lower() for c in df.columns]

        min_bars = MACD_SLOW + MACD_SIGNAL + MACD_DIV_LOOKBACK + 5
        if len(df) < min_bars:
            return StrategySignal(self.strategy_id, "HOLD", reason="insufficient_data")

        macd_ind      = ta.trend.MACD(df["close"], window_fast=MACD_FAST,
                                       window_slow=MACD_SLOW, window_sign=MACD_SIGNAL)
        df["macd"]    = macd_ind.macd()
        df["macd_sig"]= macd_ind.macd_signal()
        df["macd_h"]  = macd_ind.macd_diff()   # histogram
        df["atr"]     = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=ATR_PERIOD)

        if df["macd_h"].iloc[-MACD_DIV_LOOKBACK:].isna().all():
            return StrategySignal(self.strategy_id, "HOLD", reason="macd_nan")

        atr = df["atr"].iloc[-1]
        if pd.isna(atr) or atr <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="atr_nan")

        # ── Bearish divergence: price HH tapi MACD histogram LH ─────────────
        price_peaks = _find_peaks(df["high"], MACD_DIV_LOOKBACK)
        macd_peaks  = _find_peaks(df["macd_h"], MACD_DIV_LOOKBACK)

        bear_div = False
        if len(price_peaks) >= 2 and len(macd_peaks) >= 2:
            p1, p2 = price_peaks[-2], price_peaks[-1]   # p2 lebih baru
            m1, m2 = macd_peaks[-2],  macd_peaks[-1]
            # Price buat HH (p2 > p1) tapi MACD buat LH (m2 < m1)
            if (df["high"].iloc[p2] > df["high"].iloc[p1] and
                    df["macd_h"].iloc[m2] < df["macd_h"].iloc[m1] and
                    p2 >= len(df) - 5):    # peak harus baru (dalam 5 candle terakhir)
                bear_div = True

        # ── Bullish divergence: price LL tapi MACD histogram HL ─────────────
        price_troughs = _find_troughs(df["low"], MACD_DIV_LOOKBACK)
        macd_troughs  = _find_troughs(df["macd_h"], MACD_DIV_LOOKBACK)

        bull_div = False
        if len(price_troughs) >= 2 and len(macd_troughs) >= 2:
            t1, t2 = price_troughs[-2], price_troughs[-1]
            n1, n2 = macd_troughs[-2],  macd_troughs[-1]
            if (df["low"].iloc[t2] < df["low"].iloc[t1] and
                    df["macd_h"].iloc[n2] > df["macd_h"].iloc[n1] and
                    t2 >= len(df) - 5):
                bull_div = True

        sl_dist    = atr * MACD_SL_ATR_MULT
        tp_dist    = sl_dist * MACD_RR
        confidence = 0.65   # divergence cukup reliable, tapi butuh konfirmasi manual

        if bull_div:
            log.info(f"[{pair}] MACD_DIV BUY | bullish divergence detected")
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="BUY",
                order_type="MARKET",
                sl_distance=round(sl_dist, 5),
                tp_distance=round(tp_dist, 5),
                reason=f"macd_bull_divergence|macd_h:{df['macd_h'].iloc[-1]:.5f}",
                confidence=confidence,
            )

        if bear_div:
            log.info(f"[{pair}] MACD_DIV SELL | bearish divergence detected")
            return StrategySignal(
                strategy_id=self.strategy_id,
                direction="SELL",
                order_type="MARKET",
                sl_distance=round(sl_dist, 5),
                tp_distance=round(tp_dist, 5),
                reason=f"macd_bear_divergence|macd_h:{df['macd_h'].iloc[-1]:.5f}",
                confidence=confidence,
            )

        return StrategySignal(
            self.strategy_id, "HOLD",
            reason=f"no_divergence|macd_h:{df['macd_h'].iloc[-1]:.5f}",
        )
