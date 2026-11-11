"""
Strategy — 3 EMA + Fibonacci Confluence.
EMA stack (50/100/150) konfirmasi trend + LIMIT entry di level fibo yang
bertepatan dengan EMA50/100 (zona pullback berkualitas tinggi).

Setup:
  BUY  → EMA50 > EMA100 > EMA150, pullback ke fibo 38.2-61.8% dekat EMA50/100
  SELL → EMA50 < EMA100 < EMA150, rally ke fibo 38.2-61.8% dekat EMA50/100

Entry : LIMIT di level fibo+EMA confluence terdekat
SL    : Di luar EMA150 + buffer ATR
TP    : SL × RR

Filter:
- ADX >= EMA3_FIBO_ADX_MIN (hindari sideways)
- Confirmation candle: candle sebelumnya menyentuh zona + close kembali keluar
"""
from __future__ import annotations
import logging
import pandas as pd
import ta
from .base import BaseStrategy, StrategySignal
from config import (
    ATR_PERIOD,
    EMA3_FIBO_FAST, EMA3_FIBO_MID, EMA3_FIBO_SLOW,
    EMA3_FIBO_SWING_LOOKBACK, EMA3_FIBO_EMA_TOL_ATR,
    EMA3_FIBO_PROXIMITY_ATR, EMA3_FIBO_SL_BUFFER_ATR,
    EMA3_FIBO_RR, EMA3_FIBO_LEVELS,
    EMA3_FIBO_ADX_MIN, EMA3_FIBO_CONFIRM_CANDLE, EMA3_FIBO_TOUCH_TOL_ATR,
    EMA3_FIBO_MIN_SPREAD_ATR,
)

log = logging.getLogger(__name__)


class Strategy3EmaFibo(BaseStrategy):
    strategy_id = "EMA3_FIBO"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:
        df = pd.DataFrame(ohlcv)
        df.columns = [c.lower() for c in df.columns]

        min_bars = EMA3_FIBO_SLOW + EMA3_FIBO_SWING_LOOKBACK + 10
        if len(df) < min_bars:
            return StrategySignal(self.strategy_id, "HOLD", reason="insufficient_data")

        # ── Indikator ────────────────────────────────────────────────────────
        atr    = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=ATR_PERIOD).iloc[-1]
        ema50  = ta.trend.ema_indicator(df["close"], window=EMA3_FIBO_FAST).iloc[-1]
        ema100 = ta.trend.ema_indicator(df["close"], window=EMA3_FIBO_MID).iloc[-1]
        ema150 = ta.trend.ema_indicator(df["close"], window=EMA3_FIBO_SLOW).iloc[-1]
        adx    = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14).adx().iloc[-1]

        if any(pd.isna(x) for x in [atr, ema50, ema100, ema150, adx]) or atr <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="indicator_nan")

        # ── ADX filter: hindari sideways ─────────────────────────────────────
        if adx < EMA3_FIBO_ADX_MIN:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"adx_too_low:{adx:.1f}<{EMA3_FIBO_ADX_MIN}",
            )

        curr_price = df["close"].iloc[-1]

        # ── EMA Stack: semua 3 harus aligned ─────────────────────────────────
        bullish = ema50 > ema100 > ema150
        bearish = ema50 < ema100 < ema150
        if not bullish and not bearish:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"no_ema_stack|e50={ema50:.5f}|e100={ema100:.5f}|e150={ema150:.5f}",
            )

        # ── EMA Spread: trend harus cukup kuat ───────────────────────────────
        ema_spread_atr = abs(ema50 - ema150) / atr
        if ema_spread_atr < EMA3_FIBO_MIN_SPREAD_ATR:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"ema_spread_too_small:{ema_spread_atr:.2f}<{EMA3_FIBO_MIN_SPREAD_ATR}",
            )

        direction = "BUY" if bullish else "SELL"

        # ── Swing detection: cari impulse terbaru ────────────────────────────
        recent = df.iloc[-EMA3_FIBO_SWING_LOOKBACK:]
        sh_pos = int(recent["high"].values.argmax())
        sl_pos = int(recent["low"].values.argmin())

        # BUY butuh swing_high lebih baru (impulse bullish → price sedang pullback)
        # SELL butuh swing_low lebih baru (impulse bearish → price sedang rally)
        if direction == "BUY" and sh_pos <= sl_pos:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"no_bullish_impulse|sh={sh_pos}<=sl={sl_pos}",
            )
        if direction == "SELL" and sl_pos <= sh_pos:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"no_bearish_impulse|sl={sl_pos}<=sh={sh_pos}",
            )

        swing_high = float(recent["high"].max())
        swing_low  = float(recent["low"].min())
        rng = swing_high - swing_low
        if rng <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="swing_range_zero")

        # ── Level Fibonacci dari impulse swing ───────────────────────────────
        if direction == "BUY":
            fibo_map = {f: swing_high - f * rng for f in EMA3_FIBO_LEVELS}
        else:
            fibo_map = {f: swing_low  + f * rng for f in EMA3_FIBO_LEVELS}

        # ── Filter 1: fibo harus dekat EMA50 atau EMA100 ─────────────────────
        ema_tol   = EMA3_FIBO_EMA_TOL_ATR * atr
        proximity = EMA3_FIBO_PROXIMITY_ATR * atr
        candidates = []
        for pct, lvl in fibo_map.items():
            near_ema = abs(lvl - ema50) <= ema_tol or abs(lvl - ema100) <= ema_tol
            if not near_ema:
                continue
            if direction == "BUY"  and not (lvl < curr_price and curr_price - lvl <= proximity):
                continue
            if direction == "SELL" and not (lvl > curr_price and lvl - curr_price <= proximity):
                continue
            candidates.append((pct, lvl))

        if not candidates:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"no_fibo_ema_confluence|fibs={[f'{v:.5f}' for v in fibo_map.values()]}|ema50={ema50:.5f}|tol={ema_tol:.5f}",
            )

        # Pilih level fibo terkuat (0.618 > 0.5 > 0.382)
        candidates.sort(key=lambda x: -x[0])
        best_pct, entry_price = candidates[0]

        # ── Filter 2: Confirmation candle — rejection di zona ─────────────────
        # Candle sebelumnya harus menyentuh zona entry (wick), lalu close keluar
        # Ini memastikan zona sudah diuji dan ada penolakan harga
        if EMA3_FIBO_CONFIRM_CANDLE and len(df) >= 2:
            prev = df.iloc[-2]
            curr = df.iloc[-1]
            touch_tol = EMA3_FIBO_TOUCH_TOL_ATR * atr

            if direction == "BUY":
                # Prev wick turun menyentuh zona, curr close di atas zona
                prev_touched  = prev["low"] <= entry_price + touch_tol
                curr_rejected = curr["close"] > entry_price
                confirmed = prev_touched and curr_rejected
            else:
                # Prev wick naik menyentuh zona, curr close di bawah zona
                prev_touched  = prev["high"] >= entry_price - touch_tol
                curr_rejected = curr["close"] < entry_price
                confirmed = prev_touched and curr_rejected

            if not confirmed:
                return StrategySignal(
                    self.strategy_id, "HOLD",
                    reason=f"no_rejection_candle|entry={entry_price:.5f}|prev_low={prev['low']:.5f}|curr_close={curr['close']:.5f}",
                )

        # ── SL: di luar EMA150 + buffer ──────────────────────────────────────
        sl_buf = EMA3_FIBO_SL_BUFFER_ATR * atr
        if direction == "BUY":
            sl_distance = entry_price - (ema150 - sl_buf)
        else:
            sl_distance = (ema150 + sl_buf) - entry_price

        if sl_distance <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="sl_distance_zero")

        tp_distance = sl_distance * EMA3_FIBO_RR

        # ── Confidence ───────────────────────────────────────────────────────
        # 5 kondisi ketat sudah lolos: stack + spread + ADX + impulse + rejection
        # Base lebih tinggi karena signal sudah difilter sangat ketat
        base_conf  = 0.65 + (best_pct - 0.5) / (0.618 - 0.5) * 0.10  # 0.65 (50%) – 0.75 (61.8%)
        adx_bonus  = min((adx - EMA3_FIBO_ADX_MIN) / 40.0, 0.08)      # max +0.08 untuk ADX kuat
        ema_spread = abs(ema50 - ema150) / atr
        spread_bon = min(ema_spread / 10.0, 0.07)                       # max +0.07 untuk trend kuat
        confidence = min(base_conf + adx_bonus + spread_bon, 0.90)

        log.info(
            f"[{pair}] EMA3_FIBO {direction} | fibo={best_pct:.3f} @ {entry_price:.5f} "
            f"| ema50={ema50:.5f} ema150={ema150:.5f} | adx={adx:.1f} "
            f"| sl={sl_distance:.5f} | conf={confidence:.2f}"
        )

        return StrategySignal(
            strategy_id=self.strategy_id,
            direction=direction,
            order_type="LIMIT",
            entry_price=round(entry_price, 5),
            sl_distance=round(sl_distance, 5),
            tp_distance=round(tp_distance, 5),
            reason=(
                f"ema3_fibo_{direction.lower()}"
                f"|fibo:{best_pct:.3f}|adx:{adx:.0f}"
                f"|stack:{'bull' if bullish else 'bear'}"
            ),
            confidence=confidence,
        )
