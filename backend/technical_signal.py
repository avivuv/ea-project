from __future__ import annotations
import pandas as pd
import ta
from dataclasses import dataclass
from typing import Literal
from config import (
    EMA_FAST, EMA_SLOW, RSI_PERIOD, ATR_PERIOD, ADX_PERIOD, ADX_MIN_LEVEL,
    RSI_BUY_MIN, RSI_BUY_MAX, RSI_SELL_MIN, RSI_SELL_MAX,
    SL_ATR_MULTIPLIER, TP_ATR_MULTIPLIER, PAIR_RSI_CONFIG,
    ATR_MIN_THRESHOLD, BODY_MULT,
    EMA_SLOPE_PERIOD, EMA_SLOPE_MIN_PCT,
    VOLUME_SPIKE_MULT, VOLUME_LOOKBACK,
    ENABLE_RSI_DIVERGENCE, DIVERGENCE_LOOKBACK,
    ENABLE_PULLBACK_ENTRY, PULLBACK_ATR_MULT,
)

SignalDirection = Literal["BUY", "SELL", "HOLD"]


@dataclass
class TechnicalSignal:
    direction: SignalDirection
    ema_fast: float
    ema_slow: float
    rsi: float
    atr: float
    adx: float
    sl_distance: float
    tp_distance: float
    reason: str


def _compute_adx_dmi(df: pd.DataFrame) -> tuple[float, float, float]:
    """Return (adx, plus_di, minus_di) dari candle terakhir."""
    adx_indicator = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=ADX_PERIOD)
    adx     = adx_indicator.adx().iloc[-1]
    plus_di = adx_indicator.adx_pos().iloc[-1]
    minus_di = adx_indicator.adx_neg().iloc[-1]
    return adx, plus_di, minus_di


def _ema_slope(ema_series: pd.Series) -> float:
    """Return slope EMA50 relatif terhadap harga (pct). Positif = naik, negatif = turun."""
    if len(ema_series) < EMA_SLOPE_PERIOD + 1:
        return 0.0
    past = ema_series.iloc[-1 - EMA_SLOPE_PERIOD]
    current = ema_series.iloc[-1]
    if pd.isna(past) or pd.isna(current) or past == 0:
        return 0.0
    return (current - past) / past


def _volume_spike(df: pd.DataFrame) -> bool:
    """Return True jika volume candle terakhir spike, atau True jika data volume kosong (bypass)."""
    if "volume" not in df.columns:
        return True
    vol_series = df["volume"]
    if vol_series.iloc[-VOLUME_LOOKBACK - 1:-1].sum() == 0:
        return True  # bypass — MT5 tidak kirim volume
    avg_vol = vol_series.iloc[-VOLUME_LOOKBACK - 1:-1].mean()
    return avg_vol > 0 and vol_series.iloc[-1] >= avg_vol * VOLUME_SPIKE_MULT


def _rsi_divergence(df: pd.DataFrame) -> tuple[bool, bool]:
    """
    Return (bullish_div, bearish_div).
    Bullish: harga lower low tapi RSI higher low → momentum melemah ke bawah.
    Bearish: harga higher high tapi RSI lower high → momentum melemah ke atas.
    """
    lookback = DIVERGENCE_LOOKBACK
    if len(df) < lookback + 2:
        return False, False
    prior_close = df["close"].iloc[-lookback - 1:-1]
    prior_rsi   = df["rsi"].iloc[-lookback - 1:-1]
    curr_close  = df["close"].iloc[-1]
    curr_rsi    = df["rsi"].iloc[-1]
    if prior_rsi.isna().any() or pd.isna(curr_rsi):
        return False, False
    bull_div = curr_close < prior_close.min() and curr_rsi > prior_rsi.min()
    bear_div = curr_close > prior_close.max() and curr_rsi < prior_rsi.max()
    return bull_div, bear_div


def _htf_trend(htf_ohlcv: list) -> str | None:
    """
    Return 'BULLISH', 'BEARISH', atau None kalau data tidak cukup.
    Cek EMA50 vs EMA200 di HTF.
    """
    if not htf_ohlcv or len(htf_ohlcv) < EMA_SLOW + 10:
        return None
    df = pd.DataFrame(htf_ohlcv)
    df.columns = [c.lower() for c in df.columns]
    ema_fast = ta.trend.ema_indicator(df["close"], window=EMA_FAST).iloc[-1]
    ema_slow = ta.trend.ema_indicator(df["close"], window=EMA_SLOW).iloc[-1]
    if pd.isna(ema_fast) or pd.isna(ema_slow):
        return None
    return "BULLISH" if ema_fast > ema_slow else "BEARISH"


def compute_signal(ohlcv: list, pair: str = "DEFAULT", htf_ohlcv: list = None) -> TechnicalSignal:
    df = pd.DataFrame(ohlcv)
    df.columns = [c.lower() for c in df.columns]

    if len(df) < EMA_SLOW + 10:
        return TechnicalSignal("HOLD", 0, 0, 0, 0, 0, 0, 0, "insufficient_data")

    df["ema_fast"] = ta.trend.ema_indicator(df["close"], window=EMA_FAST)
    df["ema_slow"] = ta.trend.ema_indicator(df["close"], window=EMA_SLOW)
    df["rsi"]      = ta.momentum.rsi(df["close"], window=RSI_PERIOD)
    df["atr"]      = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=ATR_PERIOD)

    last      = df.iloc[-1]
    ema_fast  = last["ema_fast"]
    ema_slow  = last["ema_slow"]
    rsi       = last["rsi"]
    atr       = last["atr"]
    close     = last["close"]
    open_price = last["open"]

    if any(pd.isna(v) for v in [ema_fast, ema_slow, rsi, atr]):
        return TechnicalSignal("HOLD", 0, 0, 0, 0, 0, 0, 0, "indicator_nan")

    # ATR minimum threshold — filter pasar flat/choppy
    atr_min = ATR_MIN_THRESHOLD.get(pair.upper(), ATR_MIN_THRESHOLD["DEFAULT"])
    if atr < atr_min:
        return TechnicalSignal(
            direction="HOLD",
            ema_fast=round(ema_fast, 5), ema_slow=round(ema_slow, 5),
            rsi=round(rsi, 2), atr=round(atr, 5), adx=0,
            sl_distance=0, tp_distance=0,
            reason=f"atr_too_low:{round(atr,5)}<min:{atr_min}",
        )

    # ADX filter — pastikan trend sedang kuat
    adx, plus_di, minus_di = _compute_adx_dmi(df)
    if pd.isna(adx):
        adx = 0.0
    if adx < ADX_MIN_LEVEL:
        return TechnicalSignal(
            direction="HOLD",
            ema_fast=round(ema_fast, 5), ema_slow=round(ema_slow, 5),
            rsi=round(rsi, 2), atr=round(atr, 5), adx=round(adx, 2),
            sl_distance=0, tp_distance=0,
            reason=f"adx_too_low:{round(adx,1)}<min:{ADX_MIN_LEVEL}",
        )

    # HTF confirmation — cek arah EMA di H1
    htf_trend = _htf_trend(htf_ohlcv) if htf_ohlcv else None

    sl_dist = atr * SL_ATR_MULTIPLIER
    tp_dist = atr * TP_ATR_MULTIPLIER

    rsi_cfg = PAIR_RSI_CONFIG.get(pair.upper(), PAIR_RSI_CONFIG["DEFAULT"])
    buy_min, buy_max   = rsi_cfg["buy_min"], rsi_cfg["buy_max"]
    sell_min, sell_max = rsi_cfg["sell_min"], rsi_cfg["sell_max"]

    candle_body = abs(close - open_price)
    upper_wick = last["high"] - max(close, open_price)
    lower_wick = min(close, open_price) - last["low"]

    candle_bullish        = close > open_price and candle_body >= atr * BODY_MULT
    candle_bearish        = close < open_price and candle_body >= atr * BODY_MULT
    candle_rejection_bull = (candle_body > 0 and lower_wick >= 2 * candle_body and lower_wick > upper_wick)
    candle_rejection_bear = (candle_body > 0 and upper_wick >= 2 * candle_body and upper_wick > lower_wick)
    ema_bullish = ema_fast > ema_slow
    dmi_bullish = plus_di > minus_di

    # EMA slope — pastikan EMA50 aktif bergerak, bukan flat
    ema_slope    = _ema_slope(df["ema_fast"])
    slope_bull   = ema_slope > EMA_SLOPE_MIN_PCT
    slope_bear   = ema_slope < -EMA_SLOPE_MIN_PCT

    # Volume spike — bypass otomatis jika MT5 tidak kirim volume
    vol_spike = _volume_spike(df)

    # ── Gate 2 Normal: BUY ────────────────────────────────────────────────────
    if (ema_bullish and dmi_bullish and slope_bull
            and buy_min <= rsi <= buy_max
            and close > ema_fast
            and (candle_bullish or candle_rejection_bull)
            and vol_spike
            and (htf_trend is None or htf_trend == "BULLISH")):
        htf_note    = f"+htf_{htf_trend}" if htf_trend else "+htf_skip"
        candle_note = "rejection_bull" if candle_rejection_bull and not candle_bullish else "bullish_candle"
        return TechnicalSignal(
            direction="BUY",
            ema_fast=round(ema_fast, 5), ema_slow=round(ema_slow, 5),
            rsi=round(rsi, 2), atr=round(atr, 5), adx=round(adx, 2),
            sl_distance=round(sl_dist, 5), tp_distance=round(tp_dist, 5),
            reason=f"ema_bullish+dmi_bull+adx_{round(adx,1)}+rsi_ok+{candle_note}+slope+vol{htf_note}",
        )

    # ── Gate 2 Normal: SELL ───────────────────────────────────────────────────
    if (not ema_bullish and not dmi_bullish and slope_bear
            and sell_min <= rsi <= sell_max
            and close < ema_fast
            and (candle_bearish or candle_rejection_bear)
            and vol_spike
            and (htf_trend is None or htf_trend == "BEARISH")):
        htf_note    = f"+htf_{htf_trend}" if htf_trend else "+htf_skip"
        candle_note = "rejection_bear" if candle_rejection_bear and not candle_bearish else "bearish_candle"
        return TechnicalSignal(
            direction="SELL",
            ema_fast=round(ema_fast, 5), ema_slow=round(ema_slow, 5),
            rsi=round(rsi, 2), atr=round(atr, 5), adx=round(adx, 2),
            sl_distance=round(sl_dist, 5), tp_distance=round(tp_dist, 5),
            reason=f"ema_bearish+dmi_bear+adx_{round(adx,1)}+rsi_ok+{candle_note}+slope+vol{htf_note}",
        )

    # ── Mode: Pullback to EMA (ENABLE_PULLBACK_ENTRY=true) ────────────────────
    # Entry saat harga bounce dari EMA50 dengan rejection candle
    if ENABLE_PULLBACK_ENTRY:
        near_ema = abs(close - ema_fast) <= atr * PULLBACK_ATR_MULT
        if (ema_bullish and dmi_bullish and slope_bull and near_ema
                and candle_rejection_bull
                and (htf_trend is None or htf_trend == "BULLISH")):
            htf_note = f"+htf_{htf_trend}" if htf_trend else "+htf_skip"
            return TechnicalSignal(
                direction="BUY",
                ema_fast=round(ema_fast, 5), ema_slow=round(ema_slow, 5),
                rsi=round(rsi, 2), atr=round(atr, 5), adx=round(adx, 2),
                sl_distance=round(sl_dist, 5), tp_distance=round(tp_dist, 5),
                reason=f"pullback_ema+rejection_bull+adx_{round(adx,1)}+rsi_{round(rsi,1)}{htf_note}",
            )
        if (not ema_bullish and not dmi_bullish and slope_bear and near_ema
                and candle_rejection_bear
                and (htf_trend is None or htf_trend == "BEARISH")):
            htf_note = f"+htf_{htf_trend}" if htf_trend else "+htf_skip"
            return TechnicalSignal(
                direction="SELL",
                ema_fast=round(ema_fast, 5), ema_slow=round(ema_slow, 5),
                rsi=round(rsi, 2), atr=round(atr, 5), adx=round(adx, 2),
                sl_distance=round(sl_dist, 5), tp_distance=round(tp_dist, 5),
                reason=f"pullback_ema+rejection_bear+adx_{round(adx,1)}+rsi_{round(rsi,1)}{htf_note}",
            )

    # ── Mode: RSI Divergence (ENABLE_RSI_DIVERGENCE=true) ────────────────────
    # Entry saat divergence RSI/price terdeteksi — tidak butuh EMA crossover
    if ENABLE_RSI_DIVERGENCE:
        bull_div, bear_div = _rsi_divergence(df)
        if (bull_div and candle_rejection_bull
                and (htf_trend is None or htf_trend == "BULLISH")):
            htf_note = f"+htf_{htf_trend}" if htf_trend else "+htf_skip"
            return TechnicalSignal(
                direction="BUY",
                ema_fast=round(ema_fast, 5), ema_slow=round(ema_slow, 5),
                rsi=round(rsi, 2), atr=round(atr, 5), adx=round(adx, 2),
                sl_distance=round(sl_dist, 5), tp_distance=round(tp_dist, 5),
                reason=f"rsi_divergence_bull+rejection+adx_{round(adx,1)}+rsi_{round(rsi,1)}{htf_note}",
            )
        if (bear_div and candle_rejection_bear
                and (htf_trend is None or htf_trend == "BEARISH")):
            htf_note = f"+htf_{htf_trend}" if htf_trend else "+htf_skip"
            return TechnicalSignal(
                direction="SELL",
                ema_fast=round(ema_fast, 5), ema_slow=round(ema_slow, 5),
                rsi=round(rsi, 2), atr=round(atr, 5), adx=round(adx, 2),
                sl_distance=round(sl_dist, 5), tp_distance=round(tp_dist, 5),
                reason=f"rsi_divergence_bear+rejection+adx_{round(adx,1)}+rsi_{round(rsi,1)}{htf_note}",
            )

    # Diagnosis
    ema_trend  = "bullish" if ema_bullish else "bearish"
    dmi_trend  = "bull" if dmi_bullish else "bear"
    price_side = "above" if close > ema_fast else "below"
    candle_dir = "bullish" if candle_bullish else ("bearish" if candle_bearish else "doji")
    slope_info = f"{ema_slope:.6f}"
    vol_info   = "vol_ok" if vol_spike else "vol_low"
    htf_info   = f"|htf:{htf_trend}" if htf_trend else "|htf:no_data"
    reason = (
        f"no_signal|ema:{ema_trend}|dmi:{dmi_trend}|adx:{round(adx,1)}"
        f"|rsi:{round(rsi,1)}|price:{price_side}_ema50|candle:{candle_dir}"
        f"|slope:{slope_info}|{vol_info}{htf_info}"
    )

    return TechnicalSignal(
        direction="HOLD",
        ema_fast=round(ema_fast, 5), ema_slow=round(ema_slow, 5),
        rsi=round(rsi, 2), atr=round(atr, 5), adx=round(adx, 2),
        sl_distance=0, tp_distance=0,
        reason=reason,
    )
