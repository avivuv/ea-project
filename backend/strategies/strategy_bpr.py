"""
Strategy BPR — Balanced Price Range (M15).
Konsep dari ICT/SMC trading.

BPR = zona overlap antara Bullish FVG dan Bearish FVG di level harga yang sama.
Zona ini merepresentasikan kesetimbangan institusional dari dua arah sehingga
price cenderung reject kuat saat retrace — menjadi entry high-probability.

Flow:
1. Scan M15 untuk BPR zone fresh (FVG dengan filter displacement C2)
2. HTF trend filter via H4 EMA20/EMA50 — hanya entry searah tren utama
3. Bounce confirmation wajib: candle menyentuh zona → close rejection keluar zona
4. SL di luar tepi BPR zone + buffer ATR (tight karena zona sudah presisi)
5. TP = sl_distance × BPR_RR (default 1:3)

Berbeda dari StrategyFVG:
- Mencari dua FVG saling tumpang tindih (bukan satu FVG)
- Displacement filter pada C2 (kualitas FVG lebih ketat)
- Mitigasi 50% bukan tepi zona (lebih akurat)
- RR lebih tinggi (1:3 vs 1:2) karena confluent zona
- Bounce confirmation tidak bisa dimatikan (wajib untuk M15)
"""
from __future__ import annotations
import logging
import pandas as pd
import ta
from .base import BaseStrategy, StrategySignal
from bpr_detector import find_nearest_bpr
from config import (
    ATR_PERIOD,
    BPR_LOOKBACK, BPR_MIN_GAP_ATR, BPR_MIN_GAP_ATR_PAIRS,
    BPR_PROXIMITY_ATR, BPR_DISPLACEMENT_RATIO,
    BPR_SL_BUFFER_ATR, BPR_SL_BUFFER_ATR_BY_PAIR, BPR_RR,
    BPR_MAX_AGE_BARS, BPR_MAX_CHASE_ATR, BPR_MAX_TEMPORAL_GAP,
    BPR_HTF_TREND_FILTER, BPR_HTF_EMA_FAST, BPR_HTF_EMA_SLOW,
    BPR_MAX_ZONE_GAP_ATR, BPR_MAX_ZONE_GAP_ATR_PAIRS,
    BPR_RSI_FILTER, BPR_RSI_PERIOD, BPR_RSI_BUY_MAX, BPR_RSI_SELL_MIN,
    BPR_ADX_FILTER, BPR_ADX_PERIOD, BPR_ADX_MIN,
)

log = logging.getLogger(__name__)


class StrategyBPR(BaseStrategy):
    """
    Strategy BPR — Balanced Price Range (M15 live trading).

    MARKET order saat bounce confirm dari zona BPR.
    Fallback LIMIT di midpoint jika price mendekati tapi belum ada rejection.
    """
    strategy_id = "BPR"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:
        df = pd.DataFrame(ohlcv)
        df.columns = [c.lower() for c in df.columns]

        if len(df) < BPR_LOOKBACK + 10:
            return StrategySignal(self.strategy_id, "HOLD", reason="insufficient_data")

        df["atr"] = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], window=ATR_PERIOD
        )
        df["rsi"] = ta.momentum.rsi(df["close"], window=BPR_RSI_PERIOD)
        if BPR_ADX_FILTER:
            adx_ind    = ta.trend.ADXIndicator(df["high"], df["low"], df["close"],
                                               window=BPR_ADX_PERIOD)
            df["adx"]  = adx_ind.adx()

        atr = df["atr"].iloc[-1]
        if pd.isna(atr) or atr <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="atr_nan")

        rsi         = df["rsi"].iloc[-1]

        # ── ADX filter ────────────────────────────────────────────────────────
        if BPR_ADX_FILTER:
            adx = df["adx"].iloc[-1]
            if not pd.isna(adx) and adx < BPR_ADX_MIN:
                return StrategySignal(self.strategy_id, "HOLD",
                                      reason=f"adx_low_{adx:.1f}")
        curr_price  = df["close"].iloc[-1]
        min_gap_atr = BPR_MIN_GAP_ATR_PAIRS.get(pair, BPR_MIN_GAP_ATR)

        # ── HTF Trend Filter (H4 EMA) ─────────────────────────────────────────
        htf_trend = None
        if BPR_HTF_TREND_FILTER and h4_ohlcv and len(h4_ohlcv) >= BPR_HTF_EMA_SLOW + 5:
            h4_df = pd.DataFrame(h4_ohlcv)
            h4_df.columns = [c.lower() for c in h4_df.columns]
            ema_fast = ta.trend.ema_indicator(h4_df["close"], window=BPR_HTF_EMA_FAST).iloc[-1]
            ema_slow = ta.trend.ema_indicator(h4_df["close"], window=BPR_HTF_EMA_SLOW).iloc[-1]
            if not pd.isna(ema_fast) and not pd.isna(ema_slow):
                htf_trend = "BUY" if ema_fast > ema_slow else "SELL"
                log.info(
                    f"[{pair}] BPR HTF trend={htf_trend} | "
                    f"H4 EMA{BPR_HTF_EMA_FAST}={ema_fast:.5f} "
                    f"EMA{BPR_HTF_EMA_SLOW}={ema_slow:.5f}"
                )

        allowed_buy  = htf_trend in (None, "BUY")
        allowed_sell = htf_trend in (None, "SELL")

        # ── Cari BPR zone terdekat ────────────────────────────────────────────
        max_zone_gap_atr = BPR_MAX_ZONE_GAP_ATR_PAIRS.get(pair.upper(), BPR_MAX_ZONE_GAP_ATR)

        bpr_buy = find_nearest_bpr(
            df, "BUY",  BPR_PROXIMITY_ATR, BPR_LOOKBACK,
            min_gap_atr, BPR_DISPLACEMENT_RATIO, BPR_MAX_AGE_BARS,
            BPR_MAX_TEMPORAL_GAP, max_zone_gap_atr,
        ) if allowed_buy else None

        bpr_sell = find_nearest_bpr(
            df, "SELL", BPR_PROXIMITY_ATR, BPR_LOOKBACK,
            min_gap_atr, BPR_DISPLACEMENT_RATIO, BPR_MAX_AGE_BARS,
            BPR_MAX_TEMPORAL_GAP, max_zone_gap_atr,
        ) if allowed_sell else None

        # Pilih yang lebih dekat ke harga saat ini
        bpr = None
        if bpr_buy and bpr_sell:
            dist_buy  = max(0.0, curr_price - bpr_buy.top)
            dist_sell = max(0.0, bpr_sell.bottom - curr_price)
            bpr = bpr_buy if dist_buy <= dist_sell else bpr_sell
        elif bpr_buy:
            bpr = bpr_buy
        elif bpr_sell:
            bpr = bpr_sell

        if bpr is None:
            return StrategySignal(self.strategy_id, "HOLD", reason="no_bpr_nearby")

        # ── Bounce confirmation (wajib untuk entry M15) ───────────────────────
        order_type       = "LIMIT"
        entry_price      = bpr.mid
        bounce_confirmed = False
        zone_size_pre    = bpr.top - bpr.bottom   # dipakai di bounce check & SL

        if len(df) >= 2:
            prev = df.iloc[-2]
            curr = df.iloc[-1]

            if bpr.direction == "BUY":
                # Strict bounce: wick harus mencapai midpoint zona, close harus keluar atas zona
                prev_touched  = prev["low"] <= bpr.mid
                curr_rejected = curr["close"] > bpr.top
                bounce_confirmed = prev_touched and curr_rejected
            else:
                # Strict bounce: wick harus mencapai midpoint zona, close harus keluar bawah zona
                prev_touched  = prev["high"] >= bpr.mid
                curr_rejected = curr["close"] < bpr.bottom
                bounce_confirmed = prev_touched and curr_rejected

        if bounce_confirmed:
            # Cek apakah price sudah terlalu jauh setelah bounce
            max_chase = BPR_MAX_CHASE_ATR * atr
            too_far = (
                (bpr.direction == "BUY"  and curr_price > bpr.top    + max_chase) or
                (bpr.direction == "SELL" and curr_price < bpr.bottom - max_chase)
            )
            if too_far:
                bounce_confirmed = False
                order_type  = "LIMIT"
                entry_price = bpr.mid
                log.info(
                    f"[{pair}] BPR bounce too far "
                    f"(price={curr_price:.5f} zone=[{bpr.bottom:.5f}~{bpr.top:.5f}] "
                    f"max_chase={max_chase:.5f}) → fallback LIMIT"
                )
            else:
                order_type  = "MARKET"
                entry_price = 0.0   # 0 = entry di close bar terkini

        # ── Hitung SL & TP ────────────────────────────────────────────────────
        sl_buf_mult = BPR_SL_BUFFER_ATR_BY_PAIR.get(pair.upper(), BPR_SL_BUFFER_ATR)
        buf         = sl_buf_mult * atr
        zone_size   = zone_size_pre

        if bounce_confirmed:
            # MARKET: SL anchored di tepi luar zona BPR dari posisi entry saat ini
            if bpr.direction == "BUY":
                sl_distance = curr_price - (bpr.bottom - buf)
            else:
                sl_distance = (bpr.top + buf) - curr_price
        else:
            # LIMIT: entry di midpoint zona, SL di tepi luar + buffer
            sl_distance = zone_size / 2.0 + buf

        if sl_distance <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="sl_zero")

        # ── RSI Konfirmasi (LIMIT order saja) ─────────────────────────────────
        if BPR_RSI_FILTER and order_type == "LIMIT" and not pd.isna(rsi):
            if bpr.direction == "BUY" and rsi >= BPR_RSI_BUY_MAX:
                return StrategySignal(self.strategy_id, "HOLD",
                                      reason=f"rsi_too_high_{rsi:.1f}")
            if bpr.direction == "SELL" and rsi <= BPR_RSI_SELL_MIN:
                return StrategySignal(self.strategy_id, "HOLD",
                                      reason=f"rsi_too_low_{rsi:.1f}")

        tp_distance = sl_distance * BPR_RR

        # ── Hitung Confidence ─────────────────────────────────────────────────
        # Base: kesegaran BPR (semakin baru, semakin tinggi)
        confidence = max(0.35, 1.0 - (bpr.newer_bars_ago / BPR_MAX_AGE_BARS))

        # Bonus bounce confirmation (+0.20) — signal paling kuat
        if bounce_confirmed:
            confidence = min(confidence + 0.20, 0.95)

        # Bonus zona besar: overlap >= 0.5 × ATR (imbalance signifikan)
        if zone_size >= 0.5 * atr:
            confidence = min(confidence + 0.08, 0.95)

        # Bonus complete overlap: salah satu FVG hampir sepenuhnya tercakup FVG lainnya
        bull_size = bpr.bull_fvg.top - bpr.bull_fvg.bottom
        bear_size = bpr.bear_fvg.top - bpr.bear_fvg.bottom
        min_fvg   = min(bull_size, bear_size)
        if min_fvg > 0 and zone_size >= min_fvg * 0.80:
            confidence = min(confidence + 0.05, 0.95)

        confidence = round(confidence, 3)
        mode_tag   = "bounce" if bounce_confirmed else "limit"

        log.info(
            f"[{pair}] BPR {bpr.direction} [{mode_tag}] | "
            f"zone=[{bpr.bottom:.5f}~{bpr.top:.5f}] overlap={zone_size:.5f} | "
            f"bull_age={bpr.bull_fvg.bars_ago} bear_age={bpr.bear_fvg.bars_ago} "
            f"newer={bpr.newer_bars_ago} | conf={confidence:.2f}"
        )

        return StrategySignal(
            strategy_id=self.strategy_id,
            direction=bpr.direction,
            order_type=order_type,
            entry_price=round(entry_price, 5),
            sl_distance=round(sl_distance, 5),
            tp_distance=round(tp_distance, 5),
            reason=(
                f"bpr_{mode_tag}_{'bull' if bpr.direction == 'BUY' else 'bear'}"
                f"|overlap:{zone_size:.5f}|newer:{bpr.newer_bars_ago}bars"
            ),
            confidence=confidence,
        )
