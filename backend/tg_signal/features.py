"""
Fitur kondisi pasar saat sinyal diterima — untuk mencari filter yang membedakan TP vs SL.
Semua fitur dihitung dari bar yang SUDAH close sebelum pesan (tanpa melihat masa depan),
dan dinyatakan "searah sinyal" (positif = mendukung arah sinyal).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tg_signal.backtest_tg import Bars, Signal
from tg_signal.price_resolver import resolve_zone


def _ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def _rsi(x: pd.Series, n: int = 14) -> pd.Series:
    d = x.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


class FeatureFrame:
    """Indikator dihitung sekali untuk seluruh data, lalu dibaca per sinyal."""

    def __init__(self, bars: Bars):
        df = bars.df
        self.bars = bars
        c = df["close"]
        self.rsi = _rsi(c).to_numpy()
        tr = pd.concat([df["high"] - df["low"], (df["high"] - c.shift()).abs(),
                        (df["low"] - c.shift()).abs()], axis=1).max(axis=1)
        self.atr = tr.rolling(14).mean().to_numpy()
        self.ema20_m1 = _ema(c, 20).to_numpy()
        m5c = df["close"].resample("5min").last().dropna()
        e20, e50 = _ema(m5c, 20), _ema(m5c, 50)
        # nilai EMA M5 dari bar M5 yang sudah close, dipetakan ke tiap bar M1
        trend = (e20 - e50).shift(1).reindex(df.index.floor("5min")).to_numpy()
        self.m5_trend = trend

    def at(self, sig: Signal) -> dict | None:
        b = self.bars
        s = b.first_bar_after(sig.time)
        k = s - 2                                    # bar terakhir yang pasti sudah close
        if k < 60 or s >= b.n:
            return None
        g = 1 if sig.direction == "BUY" else -1
        ref = b.o[s - 1]
        z = resolve_zone(sig.direction, sig.level_first, sig.level_last, ref=ref)
        return {
            "dist_to_zero": round(g * (ref - z.zero), 2),         # >0: harga belum sampai zona
            "mom5": round(g * (b.c[k] - b.c[k - 5]), 2),          # >0: 5 menit terakhir searah sinyal
            "mom15": round(g * (b.c[k] - b.c[k - 15]), 2),
            "last_candle": int(np.sign(g * (b.c[k] - b.o[k]))),   # 1: candle terakhir searah sinyal
            "vs_ema20_m1": round(g * (b.c[k] - self.ema20_m1[k]), 2),
            "m5_trend": int(np.sign(g * self.m5_trend[k])) if not np.isnan(self.m5_trend[k]) else 0,
            "rsi": round(float(self.rsi[k]), 1) if sig.direction == "BUY" else round(100 - float(self.rsi[k]), 1),
            "atr": round(float(self.atr[k]), 2),
            "hour_wib": (sig.time.hour + 7) % 24,
        }
