"""
Strategy OB+FVG — Order Block + Fair Value Gap confluence.
Berdasarkan dokumen 'Skenario Entry SND' — Skenario 2: Follow Trend.

Konsep:
- Order Block (OB) = candle terakhir sebelum impulse kuat (demand/supply zone)
- FVG wajib ada di zona yang sama → OB + FVG = zona kuat
- Filter HTF: EMA 50 & EMA 200 di H4 (sesuai dokumen)
- Entry LIMIT saat price kembali ke zona OB+FVG
- SL: di luar zona OB + buffer
- TP: RR 1:3 sesuai dokumen
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

import pandas as pd
import ta

from .base import BaseStrategy, StrategySignal
from config import (
    ATR_PERIOD,
    OBFVG_LOOKBACK, OBFVG_IMPULSE_ATR, OBFVG_PROXIMITY_ATR,
    OBFVG_SL_BUFFER_ATR, OBFVG_SL_BUFFER_ATR_BY_PAIR, OBFVG_RR, OBFVG_FVG_REQUIRED,
    OBFVG_HTF_EMA_FAST, OBFVG_HTF_EMA_SLOW, OBFVG_MAX_OB_AGE,
)

log = logging.getLogger(__name__)


@dataclass
class OrderBlock:
    direction: str    # "BUY" (demand) or "SELL" (supply)
    top:       float
    bottom:    float
    mid:       float
    bars_ago:  int
    has_fvg:   bool


def _find_order_blocks(df: pd.DataFrame, atr: float, lookback: int,
                       impulse_mult: float) -> list[OrderBlock]:
    """
    Deteksi Order Block di H4:
    - Bullish OB (Demand): candle bearish terakhir sebelum impulse naik kuat
    - Bearish OB (Supply): candle bullish terakhir sebelum impulse turun kuat
    - OB dianggap invalid (swept) jika ada candle setelahnya yang close di bawah bottom (BUY)
      atau close di atas top (SELL) — zona telah ditembus secara definitif
    """
    obs = []
    n = len(df)
    scan_start = max(3, n - lookback)
    closes = df["close"].values  # vectorized access

    for i in range(scan_start, n - 2):
        c    = df.iloc[i]
        next1 = df.iloc[i + 1]
        next2 = df.iloc[i + 2] if i + 2 < n else None

        body = abs(c["close"] - c["open"])
        if body <= 0:
            continue

        subsequent_closes = closes[i + 3:] if i + 3 < n else []

        # ── Bullish OB: candle bearish diikuti impulse bullish ───────────────
        if c["close"] < c["open"]:   # candle bearish
            move = next1["close"] - next1["open"]
            if next2 is not None:
                move = max(move, next2["high"] - c["low"])  # total range impulse
            if move >= impulse_mult * atr:
                top    = max(c["open"], c["close"])
                bottom = min(c["open"], c["close"])
                # FVG = gap antara high OB candle (c) dan low candle setelah impulse (next2)
                # Jika next2 ada dan low next2 > high c → gap/imbalance nyata
                has_fvg = (next2 is not None and next2["low"] > c["high"])
                # Fallback: cek gap antara low impulse dan high OB (gap lebih longgar)
                if not has_fvg:
                    has_fvg = next1["low"] > c["close"]
                # OB invalid (swept) jika ada close di bawah bottom setelah OB terbentuk
                if len(subsequent_closes) == 0 or not (subsequent_closes < bottom).any():
                    obs.append(OrderBlock("BUY", top, bottom, (top + bottom) / 2,
                                          n - 1 - i, has_fvg))

        # ── Bearish OB: candle bullish diikuti impulse bearish ───────────────
        elif c["close"] > c["open"]:  # candle bullish
            move = next1["open"] - next1["close"]
            if next2 is not None:
                move = max(move, c["high"] - next2["low"])  # total range impulse
            if move >= impulse_mult * atr:
                top    = max(c["open"], c["close"])
                bottom = min(c["open"], c["close"])
                # FVG = gap antara low OB candle (c) dan high candle setelah impulse (next2)
                has_fvg = (next2 is not None and next2["high"] < c["low"])
                if not has_fvg:
                    has_fvg = next1["high"] < c["close"]
                # OB invalid (swept) jika ada close di atas top setelah OB terbentuk
                if len(subsequent_closes) == 0 or not (subsequent_closes > top).any():
                    obs.append(OrderBlock("SELL", top, bottom, (top + bottom) / 2,
                                          n - 1 - i, has_fvg))

    return obs


class StrategyOBFVG(BaseStrategy):
    """
    OB+FVG — entry LIMIT di zona Order Block yang memiliki FVG confluence.
    Filter searah H4 EMA 50/200.
    """
    strategy_id = "OBFVG"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:

        # Butuh H4 data untuk OB detection
        if not h4_ohlcv or len(h4_ohlcv) < OBFVG_HTF_EMA_SLOW + 10:
            return StrategySignal(self.strategy_id, "HOLD", reason="no_h4_data")

        h4_df = pd.DataFrame(h4_ohlcv)
        h4_df.columns = [c.lower() for c in h4_df.columns]

        # ATR H4
        h4_atr_s = ta.volatility.average_true_range(
            h4_df["high"], h4_df["low"], h4_df["close"], window=ATR_PERIOD
        )
        h4_atr = float(h4_atr_s.iloc[-1])
        if pd.isna(h4_atr) or h4_atr <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="h4_atr_nan")

        # ── HTF Trend Filter: EMA 50/200 di H4 ──────────────────────────────
        ema_fast = ta.trend.ema_indicator(h4_df["close"], window=OBFVG_HTF_EMA_FAST).iloc[-1]
        ema_slow = ta.trend.ema_indicator(h4_df["close"], window=OBFVG_HTF_EMA_SLOW).iloc[-1]
        if pd.isna(ema_fast) or pd.isna(ema_slow):
            return StrategySignal(self.strategy_id, "HOLD", reason="ema_nan")

        htf_trend = "BUY" if ema_fast > ema_slow else "SELL"

        # ── Scan Order Blocks di H4 ──────────────────────────────────────────
        all_obs = _find_order_blocks(h4_df, h4_atr, OBFVG_LOOKBACK, OBFVG_IMPULSE_ATR)

        # Filter: searah trend + tidak terlalu tua + FVG required
        obs = [
            ob for ob in all_obs
            if ob.direction == htf_trend
            and ob.bars_ago <= OBFVG_MAX_OB_AGE
            and (not OBFVG_FVG_REQUIRED or ob.has_fvg)
        ]

        if not obs:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"no_ob|trend={htf_trend}|total_obs={len(all_obs)}"
            )

        # Current price (dari M15)
        m15_df = pd.DataFrame(ohlcv)
        m15_df.columns = [c.lower() for c in m15_df.columns]
        curr_price = float(m15_df["close"].iloc[-1])

        # Pilih OB yang paling dekat dan dalam radius proximity
        best_ob = None
        best_dist = float("inf")
        for ob in obs:
            if ob.direction == "BUY":
                # Price harus di atas OB atau mendekati dari atas
                dist = curr_price - ob.top
                in_proximity = -h4_atr * OBFVG_PROXIMITY_ATR <= dist <= h4_atr * OBFVG_PROXIMITY_ATR
            else:
                # Price harus di bawah OB atau mendekati dari bawah
                dist = ob.bottom - curr_price
                in_proximity = -h4_atr * OBFVG_PROXIMITY_ATR <= dist <= h4_atr * OBFVG_PROXIMITY_ATR

            if in_proximity and abs(dist) < best_dist:
                best_dist = abs(dist)
                best_ob = ob

        if best_ob is None:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"ob_not_near|trend={htf_trend}|obs={len(obs)}|price={curr_price:.5f}"
            )

        # ── Hitung entry, SL, TP ─────────────────────────────────────────────
        ob = best_ob
        sl_buf_mult = OBFVG_SL_BUFFER_ATR_BY_PAIR.get(pair.upper(), OBFVG_SL_BUFFER_ATR)
        buf = sl_buf_mult * h4_atr

        if ob.direction == "BUY":
            entry_price = ob.mid
            sl_distance = (ob.mid - ob.bottom) + buf
        else:
            entry_price = ob.mid
            sl_distance = (ob.top - ob.mid) + buf

        if sl_distance <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="sl_zero")

        tp_distance = sl_distance * OBFVG_RR

        # Confidence: OB dengan FVG lebih reliabel, OB lebih baru lebih baik
        confidence = 0.60
        if ob.has_fvg:
            confidence += 0.15
        confidence -= ob.bars_ago / OBFVG_MAX_OB_AGE * 0.15
        confidence = round(min(max(confidence, 0.40), 0.90), 3)

        fvg_tag = "+FVG" if ob.has_fvg else ""
        log.info(
            f"[{pair}] OBFVG {ob.direction} | zone=[{ob.bottom:.5f}~{ob.top:.5f}]{fvg_tag} "
            f"| bars_ago={ob.bars_ago} | dist={best_dist:.5f} | trend={htf_trend} | conf={confidence}"
        )

        return StrategySignal(
            strategy_id=self.strategy_id,
            direction=ob.direction,
            order_type="LIMIT",
            entry_price=round(entry_price, 5),
            sl_distance=round(sl_distance, 5),
            tp_distance=round(tp_distance, 5),
            reason=(
                f"ob_{ob.direction.lower()}{fvg_tag}"
                f"|age:{ob.bars_ago}bars|trend:{htf_trend}"
                f"|ema{OBFVG_HTF_EMA_FAST}={ema_fast:.5f}"
            ),
            confidence=confidence,
        )
