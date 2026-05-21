"""
Strategy BUMI — 4 MA Cross (SMA 5, 13, 21, 34).
Berdasarkan dokumen 'Model Entry Metode BUMI - DNDFX'.

Konsep:
- BUMI = Biru (MA5) Ungu (MA13) Merah (MA21) Ijo (MA34)
- BUY : MA5 baru saja cross di atas MA13, MA21, MA34
- SELL: MA5 baru saja cross di bawah MA13, MA21, MA34
- Mode WAIT_ORDERED: tunggu sampai 4 MA benar-benar berurutan
- Konfirmasi opsional: Engulfing candle setelah koreksi ke zona MA
"""
from __future__ import annotations
import logging
import pandas as pd
import ta
from .base import BaseStrategy, StrategySignal
from config import (
    ATR_PERIOD,
    BUMI_MA_FAST, BUMI_MA_2, BUMI_MA_3, BUMI_MA_SLOW,
    BUMI_WAIT_ORDERED, BUMI_ENGULF_CONF,
    BUMI_SL_ATR_MULT, BUMI_RR, BUMI_LOOKBACK,
)

log = logging.getLogger(__name__)


def _is_engulfing(df: pd.DataFrame, direction: str, idx: int = -1) -> bool:
    """Cek apakah candle idx adalah engulfing sesuai arah."""
    if abs(idx) > len(df) - 2:
        return False
    prev = df.iloc[idx - 1]
    curr = df.iloc[idx]
    if direction == "BUY":
        # Bullish engulfing: prev bearish, curr bullish, body curr > body prev
        return (prev["close"] < prev["open"] and
                curr["close"] > curr["open"] and
                curr["close"] > prev["open"] and
                curr["open"] < prev["close"])
    else:
        # Bearish engulfing: prev bullish, curr bearish
        return (prev["close"] > prev["open"] and
                curr["close"] < curr["open"] and
                curr["close"] < prev["open"] and
                curr["open"] > prev["close"])


class StrategyBUMI(BaseStrategy):
    """
    Strategy BUMI — entry saat MA5 cross ketiga MA lainnya.
    Mode WAIT_ORDERED: tambah syarat 4 MA harus berurutan.
    """
    strategy_id = "BUMI"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:
        df = pd.DataFrame(ohlcv)
        df.columns = [c.lower() for c in df.columns]

        min_bars = BUMI_MA_SLOW + BUMI_LOOKBACK + 5
        if len(df) < min_bars:
            return StrategySignal(self.strategy_id, "HOLD", reason="insufficient_data")

        # ── Hitung 4 SMA ─────────────────────────────────────────────────────
        df["ma5"]  = df["close"].rolling(BUMI_MA_FAST).mean()
        df["ma13"] = df["close"].rolling(BUMI_MA_2).mean()
        df["ma21"] = df["close"].rolling(BUMI_MA_3).mean()
        df["ma34"] = df["close"].rolling(BUMI_MA_SLOW).mean()
        df["atr"]  = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], window=ATR_PERIOD
        )

        # Ambil 2 candle terakhir untuk deteksi cross
        cur  = df.iloc[-1]
        prev = df.iloc[-2]

        for col in ["ma5", "ma13", "ma21", "ma34", "atr"]:
            if pd.isna(cur[col]):
                return StrategySignal(self.strategy_id, "HOLD", reason="ma_nan")

        atr = cur["atr"]
        if atr <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="atr_zero")

        ma5_cur, ma13_cur, ma21_cur, ma34_cur = cur["ma5"], cur["ma13"], cur["ma21"], cur["ma34"]
        ma5_prv = prev["ma5"]

        # ── Deteksi cross MA5 terhadap semua MA ──────────────────────────────
        # BUY: MA5 baru cross di atas MA13, MA21, MA34
        cross_buy  = (ma5_prv <= ma13_cur or ma5_prv <= ma21_cur or ma5_prv <= ma34_cur) and \
                     (ma5_cur > ma13_cur and ma5_cur > ma21_cur and ma5_cur > ma34_cur)

        # SELL: MA5 baru cross di bawah MA13, MA21, MA34
        cross_sell = (ma5_prv >= ma13_cur or ma5_prv >= ma21_cur or ma5_prv >= ma34_cur) and \
                     (ma5_cur < ma13_cur and ma5_cur < ma21_cur and ma5_cur < ma34_cur)

        # Fallback: jika tidak ada cross baru, cek apakah cross terjadi dalam LOOKBACK candle terakhir
        if not cross_buy and not cross_sell:
            lookback = min(BUMI_LOOKBACK, len(df) - 2)
            for i in range(2, lookback + 2):
                c = df.iloc[-i]
                p = df.iloc[-i - 1]
                if any(pd.isna([c["ma5"], c["ma13"], c["ma21"], c["ma34"],
                                p["ma5"]])):
                    continue
                if (p["ma5"] <= c["ma13"] or p["ma5"] <= c["ma21"] or p["ma5"] <= c["ma34"]) and \
                   (c["ma5"] > c["ma13"] and c["ma5"] > c["ma21"] and c["ma5"] > c["ma34"]):
                    cross_buy = True
                    break
                if (p["ma5"] >= c["ma13"] or p["ma5"] >= c["ma21"] or p["ma5"] >= c["ma34"]) and \
                   (c["ma5"] < c["ma13"] and c["ma5"] < c["ma21"] and c["ma5"] < c["ma34"]):
                    cross_sell = True
                    break

        if not cross_buy and not cross_sell:
            return StrategySignal(self.strategy_id, "HOLD", reason="no_ma_cross")

        direction = "BUY" if cross_buy else "SELL"

        # ── Mode: Menunggu Urutan (4 MA berurutan) ───────────────────────────
        if BUMI_WAIT_ORDERED:
            if direction == "BUY":
                ordered = ma5_cur > ma13_cur > ma21_cur > ma34_cur
            else:
                ordered = ma5_cur < ma13_cur < ma21_cur < ma34_cur

            if not ordered:
                return StrategySignal(
                    self.strategy_id, "HOLD",
                    reason=f"bumi_wait_ordered|ma5={ma5_cur:.5f}|ma13={ma13_cur:.5f}"
                           f"|ma21={ma21_cur:.5f}|ma34={ma34_cur:.5f}"
                )

        # ── Konfirmasi Engulfing (opsional) ──────────────────────────────────
        reason_parts = [f"bumi_{direction.lower()}|cross|ma5={ma5_cur:.5f}"]
        if BUMI_ENGULF_CONF:
            if not _is_engulfing(df, direction, idx=-1):
                return StrategySignal(
                    self.strategy_id, "HOLD",
                    reason="bumi_wait_engulfing"
                )
            reason_parts.append("engulfing")

        # ── Confidence: semakin berurutan semakin tinggi ─────────────────────
        if direction == "BUY":
            spread = (ma5_cur - ma34_cur) / ma34_cur if ma34_cur else 0
        else:
            spread = (ma34_cur - ma5_cur) / ma34_cur if ma34_cur else 0

        confidence = min(0.5 + spread * 100, 0.85)

        if BUMI_WAIT_ORDERED:
            reason_parts.append("ordered")

        sl_distance = BUMI_SL_ATR_MULT * atr
        tp_distance = sl_distance * BUMI_RR

        log.info(
            f"[{pair}] BUMI {direction} | MA5={ma5_cur:.5f} MA13={ma13_cur:.5f} "
            f"MA21={ma21_cur:.5f} MA34={ma34_cur:.5f} | conf={confidence:.2f}"
        )

        return StrategySignal(
            strategy_id=self.strategy_id,
            direction=direction,
            order_type="MARKET",
            entry_price=0.0,
            sl_distance=round(sl_distance, 5),
            tp_distance=round(tp_distance, 5),
            reason="|".join(reason_parts),
            confidence=round(confidence, 3),
        )
