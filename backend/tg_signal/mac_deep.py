"""Pendalaman Trend MA Cross (asal: BUMI DNDFX; SMA 5/13/21/34) di H4: variasi SL, filter trend, pair lain, train/test.

Entry (dokumen DNDFX): cross = MA5 melewati 13/21/34; urut = tunggu 5>13>21>34;
langsung = close candle trigger; engulf = koreksi lalu engulfing ketat (close > high candle sebelumnya).
Exit: MA5 cross balik ke sisi lain ketiga MA (close bar), atau SL. Satu posisi sekaligus.

SL : pct0.3 (0.3% harga) | atr1.5/atr2/atr3 (ATR14 TF) | swing (low/high 10 bar + 0.2 ATR)
Filter: none | ema200 (close di sisi EMA200) | slope (EMA200 naik/turun 10 bar)
Train 2014-2020, test 2021-2026.

    python -m tg_signal.mac_deep            # semua pair, H4
    python -m tg_signal.mac_deep --tf 1D
"""
from __future__ import annotations

import argparse
from itertools import product

import numpy as np
import pandas as pd

from tg_signal.dndfx_backtest import DATA, atr, exit_sim, resample

PAIRS = ("XAUUSD", "XAGUSD", "EURUSD", "USDJPY", "BTCUSD", "US500")
SPLIT = pd.Timestamp("2021-01-01", tz="UTC")


def load_pair(sym: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"h1_{sym}.csv.gz")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


def indicators(df: pd.DataFrame) -> dict:
    """SMA 5/13/21/34, EMA200, ATR14 + status 'up' (MA5 di sisi d ketiga MA) & 'order' (4 MA berurutan).
    Dipakai backtest (run) dan runner live (mac_live) supaya aturannya identik."""
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    s = pd.Series(c)
    a, b, e, f = (s.rolling(p).mean().to_numpy() for p in (5, 13, 21, 34))
    return dict(ma=(a, b, e, f), ema=s.ewm(span=200, adjust=False).mean().to_numpy(), atr=atr(h, l, c),
                up={1: (a > b) & (a > e) & (a > f), -1: (a < b) & (a < e) & (a < f)},
                order={1: (a > b) & (b > e) & (e > f), -1: (a < b) & (b < e) & (e < f)})


def live_signal(ind: dict, k: int, sl_atr: float = 3.0, slope_n: int = 10) -> tuple[int, float]:
    """Config terpilih (cross langsung, SL k x ATR, filter slope EMA200) di bar TF k yang sudah close.
    -> (arah, jarak SL) ; (0, 0) bila tidak ada sinyal."""
    if k <= 210:
        return 0, 0.0
    for d in (1, -1):
        u = ind["up"][d]
        if u[k] and not u[k - 1] and d * (ind["ema"][k] - ind["ema"][k - slope_n]) > 0:
            return d, float(ind["atr"][k] * sl_atr)
    return 0, 0.0


def run(df: pd.DataFrame, mode: str, ent: str, slm: str, flt: str, buy_only: bool = False) -> pd.DataFrame:
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    sp = df["spread"].to_numpy(float)
    n = len(c)
    ind = indicators(df)
    ema, at, up, order = ind["ema"], ind["atr"], ind["up"], ind["order"]
    ev = []
    for d in ((1,) if buy_only else (1, -1)):
        x = up[d]
        ev += [(k, d) for k in np.nonzero(x[1:] & ~x[:-1])[0] + 1 if k > 210]
    ev.sort()
    mir = {1: (o, h, l, c), -1: (-o, -l, -h, -c)}
    out, busy = [], -1
    for k, d in ev:
        if k <= busy:
            continue
        O, H, L, C = mir[d]
        valid = up[d]
        tb, j = None, k
        while j < n and valid[j]:
            if mode == "cross" or order[d][j]:
                tb = j
                break
            j += 1
        if tb is None:
            continue
        eb = tb if ent == "langsung" else None
        if ent == "engulf":
            j = tb + 1
            while j < n and valid[j]:
                if C[j - 1] < O[j - 1] and C[j] > O[j] and C[j] > H[j - 1]:
                    eb = j
                    break
                j += 1
        if eb is None or eb + 1 >= n:
            continue
        if flt == "ema200" and d * (c[eb] - ema[eb]) <= 0:
            continue
        if flt == "slope" and d * (ema[eb] - ema[eb - 10]) <= 0:
            continue
        entry = C[eb]
        if slm.startswith("pct"):
            dist = abs(entry) * float(slm[3:]) / 100
        elif slm.startswith("atr"):
            dist = at[eb] * float(slm[3:])
        else:  # swing
            dist = entry - L[eb - 9:eb + 1].min() + 0.2 * at[eb]
        if dist <= 0:
            continue
        sl = entry - dist
        px, ko, why = exit_sim(O, H, L, C, eb + 1, 1, sl, None, up[-d], fill_bar=False)
        r = (px - entry) / dist - sp[eb] / dist
        out.append(dict(t_in=df.index[eb], t_out=df.index[ko], dir=d, R=r, why=why))
        busy = ko
    return pd.DataFrame(out)


def pf(r: pd.Series) -> float:
    loss = -r[r < 0].sum()
    return round(r[r > 0].sum() / loss, 2) if loss > 0 else np.nan


def summarize(t: pd.DataFrame) -> dict:
    if t.empty:
        return dict(n=0)
    tr, te = t[t.t_in < SPLIT].R, t[t.t_in >= SPLIT].R
    eq = t.sort_values("t_out").R.cumsum()
    yrs = t.groupby(t.t_in.dt.year).R.sum()
    return dict(n=len(t), WR=round((t.R > 0).mean() * 100, 1), PF=pf(t.R), PF_train=pf(tr), PF_test=pf(te),
                sumR=round(t.R.sum(), 1), avgR=round(t.R.mean(), 3),
                maxDD=round((eq.cummax() - eq).max(), 1), yrs_pos=f"{(yrs > 0).sum()}/{len(yrs)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--pairs", default=",".join(PAIRS))
    a = ap.parse_args()
    pd.set_option("display.width", 220)
    grid = list(product(("cross", "urut"), ("langsung", "engulf"),
                        ("pct0.3", "atr1.5", "atr2", "atr3", "swing"), ("none", "ema200", "slope"), (False, True)))
    rows = []
    for sym in a.pairs.split(","):
        df = resample(load_pair(sym), a.tf)
        for mode, ent, slm, flt, bo in grid:
            t = run(df, mode, ent, slm, flt, bo)
            rows.append(dict(pair=sym, mode=mode, ent=ent, sl=slm, flt=flt, side="buy" if bo else "both",
                             **summarize(t)))
        res = pd.DataFrame([r for r in rows if r["pair"] == sym])
        print(f"\n== {sym} {a.tf}: 10 terbaik menurut PF_test (syarat PF_train >= 1.1, n >= 60)")
        ok = res[(res.PF_train >= 1.1) & (res.n >= 60)].sort_values("PF_test", ascending=False)
        print(ok.head(10).to_string(index=False))
        print(f"   median PF_train {res.PF_train.median():.2f} | median PF_test {res.PF_test.median():.2f}"
              f" | varian PF_test>1: {(res.PF_test > 1).mean() * 100:.0f}%")
    pd.DataFrame(rows).to_csv(DATA / f"mac_deep_{a.tf}.csv", index=False)


if __name__ == "__main__":
    main()
