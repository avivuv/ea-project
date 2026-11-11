"""
Konteks FVG saat sinyal diterima — dipakai sebagai FILTER kondisi (bukan menunggu konfirmasi).

Untuk sinyal arah D dengan zona [bottom, top] pada waktu T:
- FVG searah  : BUY ↔ FVG bullish (c3.low > c1.high), SELL ↔ FVG bearish (c3.high < c1.low),
                sudah selesai terbentuk (bar ke-3 close) sebelum T, dalam `lookback` bar terakhir,
                dan gap-nya bersinggungan dengan zona ± `tol`.
- Status isi  : "open"  = harga belum menembus seluruh gap sejak terbentuk sampai T
                "filled" = harga sudah menembus seluruh gap (FVG batal sebagai area)
                "touched" = harga sudah masuk gap tapi belum tembus (retest)
- Penghalang  : FVG BERLAWANAN yang masih terbuka di antara harga dan target TP.
Semua dihitung hanya dari data sebelum T (tanpa melihat masa depan).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15}


@dataclass
class FVG:
    bullish: bool
    lo: float
    hi: float
    done: np.datetime64      # waktu bar ke-3 close


def _tf(m1: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if minutes == 1:
        return m1
    return m1.resample(f"{minutes}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


class FVGIndex:
    def __init__(self, m1: pd.DataFrame, tf: str):
        self.tf = tf
        mins = TF_MINUTES[tf]
        b = _tf(m1, mins)
        h, l = b["high"].to_numpy(), b["low"].to_numpy()
        done = (b.index + pd.Timedelta(minutes=mins)).values.astype("datetime64[ns]")
        bull = l[2:] > h[:-2]
        bear = h[2:] < l[:-2]
        self.fvgs: list[FVG] = []
        for i in np.nonzero(bull | bear)[0]:
            j = i + 2
            if bull[i]:
                self.fvgs.append(FVG(True, h[i], l[j], done[j]))
            else:
                self.fvgs.append(FVG(False, h[j], l[i], done[j]))
        self.done = np.array([f.done for f in self.fvgs])
        # harga M1 untuk status isi (presisi)
        self.t1 = m1.index.values.astype("datetime64[ns]")
        self.h1 = m1["high"].to_numpy()
        self.l1 = m1["low"].to_numpy()

    def _status(self, f: FVG, t: np.datetime64) -> str:
        a = np.searchsorted(self.t1, f.done, side="left")
        b = np.searchsorted(self.t1, t, side="left")          # hanya bar M1 yang buka sebelum T
        b = max(a, b - 1)                                      # bar M1 terakhir yang sudah close
        if b <= a:
            return "open"
        hi, lo = self.h1[a:b].max(), self.l1[a:b].min()
        if f.bullish:
            return "filled" if lo < f.lo else ("touched" if lo <= f.hi else "open")
        return "filled" if hi > f.hi else ("touched" if hi >= f.lo else "open")

    def context(self, t, direction: str, zone_lo: float, zone_hi: float, price: float,
                tp_dist: float, lookback_bars: int = 24, tol: float = 0.5) -> dict:
        t = np.datetime64(pd.Timestamp(t).tz_convert(None).to_datetime64(), "ns")
        start = t - np.timedelta64(lookback_bars * TF_MINUTES[self.tf], "m")
        i0, i1 = np.searchsorted(self.done, start), np.searchsorted(self.done, t, side="right")
        want_bull = direction == "BUY"
        same = {"open": 0, "touched": 0, "filled": 0}
        blocker = 0
        tp = price + tp_dist if want_bull else price - tp_dist
        for f in self.fvgs[i0:i1]:
            st = self._status(f, t)
            if f.bullish == want_bull:
                if f.hi >= zone_lo - tol and f.lo <= zone_hi + tol:
                    same[st] += 1
            elif st != "filled":
                # FVG berlawanan di jalur harga → TP
                path_lo, path_hi = (price, tp) if want_bull else (tp, price)
                if f.hi >= path_lo and f.lo <= path_hi:
                    blocker += 1
        p = self.tf.lower()
        return {f"{p}_same_open": same["open"], f"{p}_same_touched": same["touched"],
                f"{p}_same_filled": same["filled"],
                f"{p}_same_valid": same["open"] + same["touched"], f"{p}_blocker": blocker}
