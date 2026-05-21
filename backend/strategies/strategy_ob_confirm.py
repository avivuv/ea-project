"""
Strategy OB_CONFIRM — SMC Multi-Timeframe Order Block Entry.

Alur kerja (MTFA):
  1. H4 — Deteksi POI: OB fresh + FVG + BOS + Premium/Discount zone + Liquidity Sweep
  2. M15 — Price tap zona H4 OB (proximity check)
  3. M15 — Deteksi CHoCH (Change of Character) searah H4 OB
  4. M15 — Cari OB baru setelah CHoCH (+ FVG)
  5. Entry LIMIT di M15 OB top/bottom → SL kecil, RR besar

Liquidity Sweep:
  - Bullish OB: candle sebelum OB memiliki wick di bawah swing low / equal low,
                tapi close kembali di atas level (stop hunt → reversal)
  - Bearish OB: wick di atas swing high / equal high, close kembali di bawah level
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

import pandas as pd
import numpy as np
import ta

from .base import BaseStrategy, StrategySignal
from choch_detector import detect_choch
from config import (
    ATR_PERIOD,
    OB_CONFIRM_ENABLED,
    OB_CONFIRM_LOOKBACK, OB_CONFIRM_IMPULSE_ATR,
    OB_CONFIRM_PROXIMITY_ATR,
    OB_CONFIRM_SL_BUFFER_ATR, OB_CONFIRM_SL_BUFFER_ATR_BY_PAIR,
    OB_CONFIRM_RR, OB_CONFIRM_MAX_OB_AGE,
    OB_CONFIRM_HTF_EMA_FAST, OB_CONFIRM_HTF_EMA_SLOW,
    OB_CONFIRM_DISABLED_PAIRS,
    OB_CONFIRM_REQUIRE_FVG, OB_CONFIRM_REQUIRE_BOS, OB_CONFIRM_REQUIRE_PD,
    OB_CONFIRM_PD_LOOKBACK, OB_CONFIRM_MIN_ZONE_ATR,
    OB_CONFIRM_CHOCH_PERIOD, OB_CONFIRM_LTF_LOOKBACK,
    OB_CONFIRM_LTF_FVG_REQ, OB_CONFIRM_LTF_SL_BUFFER,
    OB_CONFIRM_REQUIRE_SWEEP, OB_CONFIRM_SWEEP_LOOKBACK,
    OB_CONFIRM_SWEEP_WINDOW, OB_CONFIRM_SWEEP_TOL_ATR,
    OB_CONFIRM_AGE_BONUS_FVG, OB_CONFIRM_AGE_BONUS_BOS, OB_CONFIRM_AGE_BONUS_SWEEP,
)

log = logging.getLogger(__name__)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class _H4OB:
    direction:    str
    top:          float
    bottom:       float
    bars_ago:     int
    has_fvg:      bool
    has_bos:      bool
    touched:      bool   # wick pernah menyentuh zona (melemahkan)
    has_sweep:    bool   # ada liquidity sweep sebelum OB terbentuk


@dataclass
class _M15OB:
    direction: str
    top:       float
    bottom:    float
    bars_ago:  int
    has_fvg:   bool


# ── Liquidity Sweep Detection ─────────────────────────────────────────────────

def _collect_levels(df: pd.DataFrame, side: str, tolerance: float) -> list[float]:
    """
    Kumpulkan level likuiditas: swing H/L + equal H/L (dalam toleransi).
    side = "high" atau "low"
    """
    prices = df["high"].values if side == "high" else df["low"].values
    n      = len(prices)
    levels: list[float] = []

    # Swing extremes (local min/max dengan 1 bar padding)
    for i in range(1, n - 1):
        if side == "high":
            if prices[i] >= prices[i - 1] and prices[i] >= prices[i + 1]:
                levels.append(float(prices[i]))
        else:
            if prices[i] <= prices[i - 1] and prices[i] <= prices[i + 1]:
                levels.append(float(prices[i]))

    # Equal highs/lows: pasangan yang nilainya dalam toleransi (max 10 bar terpisah)
    for i in range(n):
        for j in range(i + 2, min(i + 11, n)):
            if abs(prices[i] - prices[j]) <= tolerance:
                levels.append(float((prices[i] + prices[j]) / 2))

    # Deduplikasi: singkirkan yang terlalu dekat satu sama lain
    unique: list[float] = []
    for lvl in sorted(levels, reverse=(side == "high")):
        if not any(abs(lvl - u) <= tolerance * 0.5 for u in unique):
            unique.append(lvl)
    return unique


def _detect_sweep(
    df: pd.DataFrame,
    ob_idx: int,
    direction: str,
    atr: float,
) -> bool:
    """
    True jika ada liquidity sweep sebelum OB di ob_idx.

    Bullish sweep (OB direction=BUY):
      Candle dalam SWEEP_WINDOW bar sebelum OB memiliki
      low < swing/equal low (wick tembus), dan close > level (balik).

    Bearish sweep (OB direction=SELL):
      Candle high > swing/equal high (wick tembus), close < level (balik).
    """
    tolerance  = OB_CONFIRM_SWEEP_TOL_ATR * atr
    ref_end    = max(0, ob_idx - OB_CONFIRM_SWEEP_WINDOW)
    ref_start  = max(0, ob_idx - OB_CONFIRM_SWEEP_LOOKBACK)
    swp_start  = ref_end
    swp_end    = ob_idx + 1   # inklusif OB candle sendiri

    if ref_end - ref_start < 3 or swp_end <= swp_start:
        return False

    ref_df = df.iloc[ref_start:ref_end]
    swp_df = df.iloc[swp_start:swp_end]

    side   = "low" if direction == "BUY" else "high"
    levels = _collect_levels(ref_df, side, tolerance)
    if not levels:
        return False

    for lvl in levels:
        for _, row in swp_df.iterrows():
            if direction == "BUY":
                # Wick tembus ke bawah level, tapi close kembali di atas
                if row["low"] < lvl and row["close"] > lvl:
                    return True
            else:
                # Wick tembus ke atas level, tapi close kembali di bawah
                if row["high"] > lvl and row["close"] < lvl:
                    return True

    return False


# ── H4 OB Detection ───────────────────────────────────────────────────────────

def _find_h4_obs(df: pd.DataFrame, atr: float, lookback: int,
                 impulse_mult: float) -> list[_H4OB]:
    """
    Scan H4 OB dengan semua kriteria SMC:
    fresh, FVG, BOS, touched check, dan liquidity sweep.
    """
    obs: list[_H4OB] = []
    n      = len(df)
    highs  = df["high"].values
    lows   = df["low"].values
    closes = df["close"].values

    for i in range(max(3, n - lookback), n - 2):
        c    = df.iloc[i]
        nxt1 = df.iloc[i + 1]
        nxt2 = df.iloc[i + 2] if i + 2 < n else None

        body = abs(c["close"] - c["open"])
        if body <= 0:
            continue

        sub_closes = closes[i + 3:] if i + 3 < n else []
        sub_highs  = highs[i + 3:]  if i + 3 < n else []
        sub_lows   = lows[i + 3:]   if i + 3 < n else []

        pre_highs  = highs[max(0, i - 10):i]
        pre_lows   = lows[max(0, i - 10):i]
        swing_high = float(pre_highs.max()) if len(pre_highs) > 0 else c["high"]
        swing_low  = float(pre_lows.min())  if len(pre_lows) > 0 else c["low"]

        # ── Bullish OB ───────────────────────────────────────────────────────
        if c["close"] < c["open"]:
            move = nxt1["close"] - nxt1["open"]
            if nxt2 is not None:
                move = max(move, nxt2["high"] - c["low"])
            if move < impulse_mult * atr:
                continue
            top    = max(c["open"], c["close"])
            bottom = min(c["open"], c["close"])
            if len(sub_closes) > 0 and (sub_closes < bottom).any():
                continue
            touched   = len(sub_lows) > 0 and (sub_lows < top).any()
            has_fvg   = ((nxt2 is not None and nxt2["low"] > c["high"])
                         or nxt1["low"] > c["close"])
            has_bos   = (nxt1["close"] > swing_high or
                         (nxt2 is not None and nxt2["close"] > swing_high))
            has_sweep = _detect_sweep(df, i, "BUY", atr)
            obs.append(_H4OB("BUY", top, bottom, n - 1 - i,
                             has_fvg, has_bos, touched, has_sweep))

        # ── Bearish OB ───────────────────────────────────────────────────────
        elif c["close"] > c["open"]:
            move = nxt1["open"] - nxt1["close"]
            if nxt2 is not None:
                move = max(move, c["high"] - nxt2["low"])
            if move < impulse_mult * atr:
                continue
            top    = max(c["open"], c["close"])
            bottom = min(c["open"], c["close"])
            if len(sub_closes) > 0 and (sub_closes > top).any():
                continue
            touched   = len(sub_highs) > 0 and (sub_highs > bottom).any()
            has_fvg   = ((nxt2 is not None and nxt2["high"] < c["low"])
                         or nxt1["high"] < c["close"])
            has_bos   = (nxt1["close"] < swing_low or
                         (nxt2 is not None and nxt2["close"] < swing_low))
            has_sweep = _detect_sweep(df, i, "SELL", atr)
            obs.append(_H4OB("SELL", top, bottom, n - 1 - i,
                             has_fvg, has_bos, touched, has_sweep))

    return obs


# ── Premium/Discount Filter ────────────────────────────────────────────────────

def _in_premium_discount(ob: _H4OB, df: pd.DataFrame, pd_lookback: int) -> bool:
    tail       = df.tail(pd_lookback)
    swing_high = float(tail["high"].max())
    swing_low  = float(tail["low"].min())
    if swing_high <= swing_low:
        return True
    mid = (swing_high + swing_low) / 2.0
    return ob.top < mid if ob.direction == "BUY" else ob.bottom > mid


# ── M15 OB Detection (after CHoCH) ────────────────────────────────────────────

def _find_ltf_ob(df: pd.DataFrame, direction: str, lookback: int,
                 require_fvg: bool) -> _M15OB | None:
    """Cari OB terbaik di M15 yang memicu CHoCH."""
    n          = len(df)
    scan_start = max(0, n - lookback)
    best: _M15OB | None = None
    best_score = -999.0

    for i in range(scan_start, n - 2):
        c    = df.iloc[i]
        nxt1 = df.iloc[i + 1]
        nxt2 = df.iloc[i + 2] if i + 2 < n else None

        body         = abs(c["close"] - c["open"])
        candle_range = c["high"] - c["low"]
        if candle_range <= 0 or body <= 0:
            continue
        body_ratio = body / candle_range
        if body_ratio < 0.4:
            continue

        if direction == "BUY"  and c["close"] >= c["open"]: continue
        if direction == "SELL" and c["close"] <= c["open"]: continue

        top      = max(c["open"], c["close"])
        bottom   = min(c["open"], c["close"])
        bars_ago = n - 1 - i

        has_fvg = False
        if direction == "BUY":
            has_fvg = ((nxt2 is not None and nxt2["low"] > c["high"])
                       or nxt1["low"] > c["close"])
        else:
            has_fvg = ((nxt2 is not None and nxt2["high"] < c["low"])
                       or nxt1["high"] < c["close"])

        if require_fvg and not has_fvg:
            continue

        score = body_ratio * 10 - (bars_ago / max(lookback, 1)) * 3
        if has_fvg:
            score += 2.0

        if score > best_score:
            best_score = score
            best = _M15OB(direction, top, bottom, bars_ago, has_fvg)

    return best


# ── Strategy ──────────────────────────────────────────────────────────────────

class StrategyOBConfirm(BaseStrategy):
    """
    OB_CONFIRM — SMC MTFA Golden Setup:
    H4 OB (fresh+FVG+BOS+P/D+sweep) → M15 tap → M15 CHoCH → M15 OB+FVG → LIMIT
    """
    strategy_id = "OB_CONFIRM"

    def compute(
        self,
        ohlcv:     list,
        pair:      str,
        htf_ohlcv: list | None = None,
        h4_ohlcv:  list | None = None,
    ) -> StrategySignal:

        if not OB_CONFIRM_ENABLED:
            return StrategySignal(self.strategy_id, "HOLD", reason="disabled")
        if pair.upper() in OB_CONFIRM_DISABLED_PAIRS:
            return StrategySignal(self.strategy_id, "HOLD", reason="disabled_for_pair")
        if not h4_ohlcv or len(h4_ohlcv) < OB_CONFIRM_HTF_EMA_SLOW + 10:
            return StrategySignal(self.strategy_id, "HOLD", reason="no_h4_data")
        if len(ohlcv) < OB_CONFIRM_CHOCH_PERIOD * 4 + 5:
            return StrategySignal(self.strategy_id, "HOLD", reason="insufficient_m15")

        # ── H4 setup ─────────────────────────────────────────────────────────
        h4_df = pd.DataFrame(h4_ohlcv)
        h4_df.columns = [c.lower() for c in h4_df.columns]

        h4_atr = float(ta.volatility.average_true_range(
            h4_df["high"], h4_df["low"], h4_df["close"], window=ATR_PERIOD
        ).iloc[-1])
        if pd.isna(h4_atr) or h4_atr <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="h4_atr_nan")

        ema_fast = ta.trend.ema_indicator(h4_df["close"], window=OB_CONFIRM_HTF_EMA_FAST).iloc[-1]
        ema_slow = ta.trend.ema_indicator(h4_df["close"], window=OB_CONFIRM_HTF_EMA_SLOW).iloc[-1]
        if pd.isna(ema_fast) or pd.isna(ema_slow):
            return StrategySignal(self.strategy_id, "HOLD", reason="ema_nan")
        htf_trend = "BUY" if ema_fast > ema_slow else "SELL"

        # ── Step 1: Scan H4 OB (POI) ─────────────────────────────────────────
        all_h4_obs = _find_h4_obs(h4_df, h4_atr, OB_CONFIRM_LOOKBACK, OB_CONFIRM_IMPULSE_ATR)
        min_zone   = OB_CONFIRM_MIN_ZONE_ATR * h4_atr

        valid_h4_obs: list[_H4OB] = []
        for ob in all_h4_obs:
            if ob.direction != htf_trend:                              continue
            # Max age dinamis: base + bonus per quality flag
            effective_max_age = (
                OB_CONFIRM_MAX_OB_AGE
                + (OB_CONFIRM_AGE_BONUS_FVG   if ob.has_fvg   else 0)
                + (OB_CONFIRM_AGE_BONUS_BOS   if ob.has_bos   else 0)
                + (OB_CONFIRM_AGE_BONUS_SWEEP if ob.has_sweep else 0)
            )
            if ob.bars_ago > effective_max_age:                        continue
            if (ob.top - ob.bottom) < min_zone:                        continue
            if OB_CONFIRM_REQUIRE_FVG    and not ob.has_fvg:           continue
            if OB_CONFIRM_REQUIRE_BOS    and not ob.has_bos:           continue
            if OB_CONFIRM_REQUIRE_SWEEP  and not ob.has_sweep:         continue
            if OB_CONFIRM_REQUIRE_PD and not _in_premium_discount(
                    ob, h4_df, OB_CONFIRM_PD_LOOKBACK):                continue
            valid_h4_obs.append(ob)

        # Log semua H4 OB untuk review manual
        if all_h4_obs:
            def _tag(o: _H4OB) -> str:
                flags = " ".join(f for f, v in [
                    ("fvg", o.has_fvg), ("bos", o.has_bos),
                    ("sweep", o.has_sweep), ("touched", o.touched),
                ] if v)
                pd_ok = _in_premium_discount(o, h4_df, OB_CONFIRM_PD_LOOKBACK)
                return (f"{o.direction}[{o.bottom:.5f}~{o.top:.5f}]"
                        f"age:{o.bars_ago}|{flags or 'raw'}|pd:{'ok' if pd_ok else 'no'}")
            log.info(f"[{pair}] OB_CONFIRM H4_obs trend={htf_trend} | "
                     + " || ".join(_tag(o) for o in all_h4_obs[:6]))

        if not valid_h4_obs:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"no_valid_h4_ob|trend={htf_trend}|total={len(all_h4_obs)}"
            )

        # ── Step 2: Proximity check ke H4 OB ─────────────────────────────────
        m15_df     = pd.DataFrame(ohlcv)
        m15_df.columns = [c.lower() for c in m15_df.columns]
        curr_price = float(m15_df["close"].iloc[-1])
        proximity  = OB_CONFIRM_PROXIMITY_ATR * h4_atr

        target_h4_ob: _H4OB | None = None
        best_dist    = float("inf")
        nearest_ob   = None
        nearest_dist = float("inf")

        for ob in valid_h4_obs:
            mid      = (ob.top + ob.bottom) / 2
            raw_dist = abs(curr_price - mid)
            dist_to_zone = (
                max(0.0, curr_price - ob.top)
                if ob.direction == "BUY"
                else max(0.0, ob.bottom - curr_price)
            )
            in_zone = ob.bottom <= curr_price <= ob.top

            if raw_dist < nearest_dist:
                nearest_dist = raw_dist
                nearest_ob   = ob
            if (in_zone or dist_to_zone <= proximity) and raw_dist < best_dist:
                best_dist    = raw_dist
                target_h4_ob = ob

        if target_h4_ob is None:
            nearest_info = (
                f"{nearest_ob.direction}[{nearest_ob.bottom:.5f}~{nearest_ob.top:.5f}]"
                f"age:{nearest_ob.bars_ago}|dist:{nearest_dist:.5f}"
                if nearest_ob else "none"
            )
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=f"h4_ob_not_near|price={curr_price:.5f}|nearest={nearest_info}"
            )

        sweep_tag = "|sweep✓" if target_h4_ob.has_sweep else ""
        log.info(
            f"[{pair}] OB_CONFIRM price in H4_OB "
            f"{target_h4_ob.direction}[{target_h4_ob.bottom:.5f}~{target_h4_ob.top:.5f}]"
            f"age:{target_h4_ob.bars_ago}{sweep_tag} | waiting M15 CHoCH..."
        )

        # ── Step 3: CHoCH di M15 ─────────────────────────────────────────────
        bull_choch, bear_choch = detect_choch(m15_df, period=OB_CONFIRM_CHOCH_PERIOD)
        choch_ok = (
            (target_h4_ob.direction == "BUY"  and bull_choch) or
            (target_h4_ob.direction == "SELL" and bear_choch)
        )
        if not choch_ok:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=(f"waiting_choch|h4_ob={target_h4_ob.direction}"
                        f"[{target_h4_ob.bottom:.5f}~{target_h4_ob.top:.5f}]"
                        f"|bull:{bull_choch}|bear:{bear_choch}")
            )

        # ── Step 4: M15 OB setelah CHoCH ─────────────────────────────────────
        m15_ob = _find_ltf_ob(
            m15_df,
            direction=target_h4_ob.direction,
            lookback=OB_CONFIRM_LTF_LOOKBACK,
            require_fvg=OB_CONFIRM_LTF_FVG_REQ,
        )
        if m15_ob is None:
            return StrategySignal(
                self.strategy_id, "HOLD",
                reason=(f"no_m15_ob_after_choch|dir={target_h4_ob.direction}"
                        f"|fvg_req={OB_CONFIRM_LTF_FVG_REQ}")
            )

        # ── Step 5: SL, TP, Entry LIMIT ──────────────────────────────────────
        m15_atr = float(ta.volatility.average_true_range(
            m15_df["high"], m15_df["low"], m15_df["close"], window=ATR_PERIOD
        ).iloc[-1])
        if pd.isna(m15_atr) or m15_atr <= 0:
            m15_atr = h4_atr * 0.25

        ob_height   = m15_ob.top - m15_ob.bottom
        sl_distance = ob_height + OB_CONFIRM_LTF_SL_BUFFER * m15_atr
        if sl_distance <= 0:
            return StrategySignal(self.strategy_id, "HOLD", reason="sl_zero")

        tp_distance = sl_distance * OB_CONFIRM_RR
        entry_price = m15_ob.top if target_h4_ob.direction == "BUY" else m15_ob.bottom

        # ── Confidence ───────────────────────────────────────────────────────
        # Base 0.55 → naik dengan bonus quality H4+M15
        confidence = 0.55
        if target_h4_ob.has_fvg:        confidence = min(confidence + 0.10, 0.95)  # H4 FVG bonus
        if target_h4_ob.has_bos:        confidence = min(confidence + 0.08, 0.95)  # H4 BOS bonus
        if target_h4_ob.has_sweep:      confidence = min(confidence + 0.10, 0.95)  # sweep bonus
        if m15_ob.has_fvg:              confidence = min(confidence + 0.10, 0.95)  # M15 FVG bonus
        if target_h4_ob.bars_ago <= 5:  confidence = min(confidence + 0.05, 0.95)  # fresh OB bonus
        if target_h4_ob.touched:        confidence = max(confidence - 0.10, 0.40)  # touched penalti

        log.info(
            f"[{pair}] OB_CONFIRM SIGNAL {target_h4_ob.direction} "
            f"| H4_OB=[{target_h4_ob.bottom:.5f}~{target_h4_ob.top:.5f}] "
            f"fvg:{target_h4_ob.has_fvg} bos:{target_h4_ob.has_bos} "
            f"sweep:{target_h4_ob.has_sweep} age:{target_h4_ob.bars_ago} "
            f"| M15_OB=[{m15_ob.bottom:.5f}~{m15_ob.top:.5f}] "
            f"fvg:{m15_ob.has_fvg} age:{m15_ob.bars_ago} "
            f"| entry={entry_price:.5f} sl={sl_distance:.5f} "
            f"tp={tp_distance:.5f} conf={confidence:.2f}"
        )

        return StrategySignal(
            strategy_id=self.strategy_id,
            direction=target_h4_ob.direction,
            order_type="LIMIT",
            entry_price=round(entry_price, 5),
            sl_distance=round(sl_distance, 5),
            tp_distance=round(tp_distance, 5),
            reason=(
                f"ob_confirm_choch|{target_h4_ob.direction.lower()}"
                f"|sweep:{target_h4_ob.has_sweep}"
                f"|h4_age:{target_h4_ob.bars_ago}"
                f"|m15_fvg:{m15_ob.has_fvg}"
                f"|htf:{htf_trend}"
            ),
            confidence=confidence,
        )
