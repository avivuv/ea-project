"""
Pola waktu XAUUSD (H1 Exness 2014 – 2026): rata-rata gerak per jam UTC dan per hari, konsistensi per tahun,
lalu strategi "pegang posisi di jendela jam tertentu" yang dipilih di data latih (2014–2019) dan diuji 2020–2026.

    python -m intraday.seasonality

Gerak diukur dalam % harga (harga emas naik 3x, pips tidak sebanding antar tahun).
Biaya per trade: spread bar entry (min 2 pips) + slippage 0,5 pip per sisi.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tg_signal.market_data import load_m1

SPLIT = pd.Timestamp("2020-01-01", tz="UTC")
COST = 0.2 + 0.1      # harga: spread min + 2× slippage


def hourly_table(h1: pd.DataFrame) -> pd.DataFrame:
    r = (h1.close - h1.open) / h1.open * 100
    df = pd.DataFrame({"r": r, "hour": h1.index.hour, "year": h1.index.year})
    g = df.groupby("hour").r
    yr = df.pivot_table(index="hour", columns="year", values="r", aggfunc="mean")
    out = pd.DataFrame({"avg_bp": g.mean() * 100, "t": g.mean() / (g.std() / np.sqrt(g.count())),
                        "tahun_naik": (yr > 0).sum(axis=1).astype(str) + "/" + str(yr.shape[1])})
    return out.round(2)


def window_trades(h1: pd.DataFrame, start_h: int, end_h: int, direction: int, days=None) -> pd.DataFrame:
    """Entry di open bar jam start_h, exit di close bar jam end_h−1 (hari yang sama, UTC)."""
    d = h1.copy()
    d["date"] = d.index.date
    rows = []
    for day, g in d.groupby("date"):
        if days is not None and pd.Timestamp(day).dayofweek not in days:
            continue
        a, b = g[g.index.hour == start_h], g[g.index.hour == end_h - 1]
        if a.empty or b.empty:
            continue
        o, c = a.open.iloc[0], b.close.iloc[0]
        cost = max(a.spread.iloc[0], 0.2) + 0.1
        pnl = (c - o) * direction - cost
        rows.append({"time": a.index[0], "pct": pnl / o * 100, "pips": pnl / 0.1})
    return pd.DataFrame(rows)


def summarize(tr: pd.DataFrame) -> dict:
    la, uj = tr[tr.time < SPLIT], tr[tr.time >= SPLIT]
    yr = tr.groupby(tr.time.dt.year).pct.sum()
    sh = tr.pct.mean() / tr.pct.std() * np.sqrt(252) if len(tr) > 1 else 0
    return {"n": len(tr), "WR%": round(100 * (tr.pct > 0).mean()), "avg_bp": round(tr.pct.mean() * 100, 2),
            "latih_%/thn": round(la.pct.sum() / 6, 1), "uji_%/thn": round(uj.pct.sum() / max(len(uj) / 252, 1e-9), 1),
            "tahun+": f"{(yr > 0).sum()}/{len(yr)}", "sharpe": round(sh, 2)}


def main() -> None:
    pd.set_option("display.width", 220)
    h1 = load_m1("H1")
    print("== Gerak rata-rata per jam UTC (bp = 0,01%), 2014–2026 ==")
    print(hourly_table(h1).T.to_string())
    la = h1[h1.index < SPLIT]
    print("\n== Pilih jendela jam di LATIH 2014–2019 (panjang 2–8 jam, long atau short) ==")
    r = (la.close - la.open) / la.open * 100
    hr = r.groupby(la.index.hour).mean()
    cands = []
    for s in range(24):
        for n in range(2, 9):
            e = s + n
            if e > 24:
                continue
            m = hr.loc[s:e - 1].sum()
            cands.append((abs(m), s, e, int(np.sign(m))))
    cands.sort(reverse=True)
    picked, used = [], set()
    for _, s, e, d in cands:            # 5 jendela terbaik yang tidak tumpang-tindih
        if used & set(range(s, e)):
            continue
        picked.append((s, e, d)); used |= set(range(s, e))
        if len(picked) == 5:
            break
    rows = []
    for s, e, d in picked:
        tr = window_trades(h1, s, e, d)
        rows.append({"jendela UTC": f"{s:02d}-{e:02d}", "WIB": f"{(s + 7) % 24:02d}-{(e + 7) % 24:02d}",
                     "arah": "LONG" if d > 0 else "SHORT", **summarize(tr)})
    print(pd.DataFrame(rows).to_string(index=False))
    print("\n== Per hari (Senin=0), jendela terbaik pertama ==")
    s, e, d = picked[0]
    for dow in range(5):
        tr = window_trades(h1, s, e, d, days={dow})
        print(f"  hari {dow}: {summarize(tr)}")


if __name__ == "__main__":
    main()
