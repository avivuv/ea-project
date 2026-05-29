"""
Strategy 6 — Fair Value Gap (FVG).
Konsep dari ICT/SMC trading.

FVG = ketidakseimbangan (imbalance) harga yang ditinggalkan oleh
candle impulse kuat. Price sering kembali mengisi gap sebelum lanjut.

Bullish FVG → BUY saat price pull-back ke zona gap (LIMIT order)
Bearish FVG → SELL saat price rally ke zona gap (LIMIT order)

Entry logic:
1. Scan FVG fresh dalam N candle terakhir
2. Cek apakah price mendekati zona FVG (dalam proximity_atr × ATR)
3. Pasang LIMIT order di level tengah/atas FVG
4. SL: di luar zona FVG + buffer, TP: FVG size × RR
"""
from __future__ import annotations
import logging
import pandas as pd
import ta
from .base import BaseStrategy, StrategySignal
from fvg_detector import find_nearest_fvg
from config import (
    ATR_PERIOD,
    FVG_LOOKBACK, FVG_MIN_GAP_ATR, FVG_MIN_GAP_ATR_PAIRS, FVG_PROXIMITY_ATR,
    FVG_SL_BUFFER_ATR, FVG_SL_BUFFER_ATR_BY_PAIR, FVG_RR, FVG_MAX_AGE_BARS,
    FVG_HTF_TREND_FILTER, FVG_HTF_EMA_FAST, FVG_HTF_EMA_SLOW,
    FVG_CONFIRM_BOUNCE, FVG_MAX_CHASE_ATR,
)

log = logging.getLogger(__name__)


class StrategyFVG(BaseStrategy):
    """
    Strategy 6 — Fair Value Gap (FVG).
    LIMIT order saat price pull-back ke zona imbalance yang belum terisi.
    """
    strategy_id = "FVG"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:
        df = pd.DataFrame(ohlcv)
        df.columns = [c.lower() for c in df.columns]

        if len(df) < FVG_LOOKBACK + 10:
            return StrategySignal(self.strategy_id, "HOLD", reason="insufficient_data")

        df["atr"] = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=ATR_PERIOD)

        atr = df["atr"].iloc[-1]
        if pd.isna(atr) or atr <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="atr_nan")

        curr_price = df["close"].iloc[-1]
        min_gap_atr = FVG_MIN_GAP_ATR_PAIRS.get(pair, FVG_MIN_GAP_ATR)

        # ── HTF Trend Filter: hanya entry searah H4 EMA trend ───────────────
        htf_trend = None   # None = filter tidak aktif
        if FVG_HTF_TREND_FILTER and h4_ohlcv and len(h4_ohlcv) >= FVG_HTF_EMA_SLOW + 5:
            h4_df = pd.DataFrame(h4_ohlcv)
            h4_df.columns = [c.lower() for c in h4_df.columns]
            ema_fast = ta.trend.ema_indicator(h4_df["close"], window=FVG_HTF_EMA_FAST).iloc[-1]
            ema_slow = ta.trend.ema_indicator(h4_df["close"], window=FVG_HTF_EMA_SLOW).iloc[-1]
            if not pd.isna(ema_fast) and not pd.isna(ema_slow):
                htf_trend = "BUY" if ema_fast > ema_slow else "SELL"
                log.info(f"[{pair}] FVG HTF trend={htf_trend} | EMA{FVG_HTF_EMA_FAST}={ema_fast:.5f} EMA{FVG_HTF_EMA_SLOW}={ema_slow:.5f}")

        # ── Cari FVG terdekat — hanya arah yang sesuai HTF trend ────────────
        allowed_buy  = htf_trend in (None, "BUY")
        allowed_sell = htf_trend in (None, "SELL")

        fvg_buy  = find_nearest_fvg(df, "BUY",  FVG_PROXIMITY_ATR, FVG_LOOKBACK, min_gap_atr) if allowed_buy  else None
        fvg_sell = find_nearest_fvg(df, "SELL", FVG_PROXIMITY_ATR, FVG_LOOKBACK, min_gap_atr) if allowed_sell else None

        # Pilih yang lebih dekat jika keduanya ada
        fvg = None
        if fvg_buy and fvg_sell:
            dist_buy  = curr_price - fvg_buy.top
            dist_sell = fvg_sell.bottom - curr_price
            fvg = fvg_buy if dist_buy <= dist_sell else fvg_sell
        elif fvg_buy:
            fvg = fvg_buy
        elif fvg_sell:
            fvg = fvg_sell

        if fvg is None:
            return StrategySignal(self.strategy_id, "HOLD", reason="no_fvg_nearby")

        if fvg.bars_ago > FVG_MAX_AGE_BARS:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"fvg_too_old:{fvg.bars_ago}bars>max{FVG_MAX_AGE_BARS}",
            )

        # ── Bounce confirmation: tunggu candle reject zona FVG ───────────────
        # Cek apakah candle sebelumnya masuk zona dan candle terkini close keluar
        order_type  = "LIMIT"
        entry_price = fvg.mid
        bounce_confirmed = False

        if FVG_CONFIRM_BOUNCE and len(df) >= 2:
            prev = df.iloc[-2]   # candle sebelumnya
            curr = df.iloc[-1]   # candle terkini (closing)

            if fvg.direction == "BUY":
                # Price masuk zona dari atas (low prev menyentuh zona)
                # Konfirmasi: curr close kembali di ATAS top zona → rejection bullish
                prev_touched = prev["low"] <= fvg.top
                curr_rejected = curr["close"] > fvg.top
                bounce_confirmed = prev_touched and curr_rejected
            else:
                # Price masuk zona dari bawah (high prev menyentuh zona)
                # Konfirmasi: curr close kembali di BAWAH bottom zona → rejection bearish
                prev_touched = prev["high"] >= fvg.bottom
                curr_rejected = curr["close"] < fvg.bottom
                bounce_confirmed = prev_touched and curr_rejected

            if bounce_confirmed:
                # Cek apakah price sudah terlalu jauh dari zona setelah bounce
                max_chase = FVG_MAX_CHASE_ATR * atr
                too_far = (
                    (fvg.direction == "BUY"  and curr_price > fvg.top    + max_chase) or
                    (fvg.direction == "SELL" and curr_price < fvg.bottom - max_chase)
                )
                if too_far:
                    # Entry terlalu jauh dari zona → fallback LIMIT di mid zona
                    bounce_confirmed = False
                    order_type  = "LIMIT"
                    entry_price = fvg.mid
                    log.info(
                        f"[{pair}] FVG bounce too far from zone "
                        f"(price={curr_price:.5f} zone=[{fvg.bottom:.5f}~{fvg.top:.5f}] "
                        f"max_chase={max_chase:.5f}) → fallback LIMIT"
                    )
                else:
                    # Bounce valid: pasang LIMIT di zone edge bukan MARKET
                    # BUY → limit di fvg.top (batas atas), SELL → limit di fvg.bottom (batas bawah)
                    # Lebih presisi daripada chase MARKET setelah bounce candle
                    order_type  = "LIMIT"
                    entry_price = fvg.top if fvg.direction == "BUY" else fvg.bottom
            else:
                # Belum ada konfirmasi bounce — tetap LIMIT di mid zona
                order_type  = "LIMIT"
                entry_price = fvg.mid

        # ── Hitung SL & TP ───────────────────────────────────────────────────
        gap_size  = fvg.top - fvg.bottom
        sl_buf_mult = FVG_SL_BUFFER_ATR_BY_PAIR.get(pair.upper(), FVG_SL_BUFFER_ATR)
        buf       = sl_buf_mult * atr

        if bounce_confirmed:
            # LIMIT di zone edge: SL di sisi luar zona (tepi jauh + buf)
            # BUY entry di fvg.top  → SL di fvg.bottom - buf
            # SELL entry di fvg.bottom → SL di fvg.top + buf
            sl_distance = gap_size + buf
        else:
            # LIMIT order: entry di fvg.mid, gap_size/2 sudah tepat ke tepi zona
            sl_distance = gap_size / 2 + buf

        if sl_distance <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="sl_zero")

        tp_distance = sl_distance * FVG_RR

        # Confidence: bounce confirmed = lebih reliabel
        confidence = max(0.3, 1.0 - (fvg.bars_ago / FVG_LOOKBACK))
        if bounce_confirmed:
            confidence = min(confidence + 0.15, 0.95)

        mode_tag = "bounce_edge" if bounce_confirmed else "limit_mid"
        log.info(
            f"[{pair}] FVG {fvg.direction} [{mode_tag}] | zone=[{fvg.bottom:.5f}~{fvg.top:.5f}] "
            f"| gap={gap_size:.5f} | bars_ago={fvg.bars_ago} | conf={confidence:.2f}"
        )

        return StrategySignal(
            strategy_id=self.strategy_id,
            direction=fvg.direction,
            order_type=order_type,
            entry_price=round(entry_price, 5),
            sl_distance=round(sl_distance, 5),
            tp_distance=round(tp_distance, 5),
            reason=(
                f"fvg_{mode_tag}_{'bull' if fvg.direction == 'BUY' else 'bear'}"
                f"|gap:{gap_size:.5f}|age:{fvg.bars_ago}bars"
            ),
            confidence=confidence,
        )
