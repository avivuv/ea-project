"""
Filter tren TF besar: ambil sinyal BUY hanya saat tren naik, SELL hanya saat tren turun.
Entry sama dengan EA sekarang: market langsung, TP/SL dari entry (default 30/30).

    python -m tg_signal.trend_filter --day 2026-11-11     # rincian per sinyal satu hari (WIB)
    python -m tg_signal.trend_filter                       # ringkasan seluruh data M1 per paruh

Definisi tren (bar TF yang SUDAH close sebelum sinyal):
  ema   : EMA20 > EMA50 → naik, sebaliknya turun
  price : close terakhir > EMA50 → naik
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from tg_signal import backtest_tg as bt
from tg_signal import settings
from tg_signal.store import Store

TFS = {"M15": "15min", "H1": "1h", "H4": "4h"}


def trend_table(m1: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out = {}
    for name, rule in TFS.items():
        c = m1["close"].resample(rule).last().dropna()
        e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
        # geser 1 bar: nilai di indeks t = kondisi bar TF yang sudah close sebelum t
        out[name] = pd.DataFrame({"ema": np.sign(e20 - e50), "price": np.sign(c - e50)}).shift(1)
    return out


def trend_at(tt: dict, tf: str, kind: str, t: pd.Timestamp) -> int:
    v = tt[tf][kind].asof(t.floor(TFS[tf]))
    return 0 if pd.isna(v) else int(v)


def evaluate(sigs, bars, tt, tp=30, sl=30) -> pd.DataFrame:
    v = bt.Variant("MARKET", 1, tp, "entry")
    rows = []
    for sg in sigs:
        t = pd.Timestamp(sg.time)
        r = bt.simulate(sg, v, bars)
        if r["outcome"] not in ("TP", "SL", "TIMEOUT"):
            continue
        g = 1 if sg.direction == "BUY" else -1
        row = {"time": t, "sinyal": f"{sg.direction} {sg.level_first:02d}-{sg.level_last:02d}",
               "hasil": r["outcome"], "pips": r["pips"]}
        for tf in TFS:
            for kind in ("ema", "price"):
                row[f"{tf}_{kind}"] = trend_at(tt, tf, kind, t) * g    # +1 searah, −1 lawan
        rows.append(row)
    return pd.DataFrame(rows)


def rule_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.endswith("_ema") or c.endswith("_price")]


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    out = [{"aturan": "SEMUA (EA sekarang)", "trade": len(df), "WR%": 100 * (df.pips > 0).mean(),
            "pips": df.pips.sum(), "USD": df.pips.sum() * 0.1}]
    for c in rule_cols(df):
        g = df[df[c] > 0]
        out.append({"aturan": f"searah {c}", "trade": len(g), "WR%": 100 * (g.pips > 0).mean() if len(g) else 0,
                    "pips": g.pips.sum(), "USD": g.pips.sum() * 0.1})
    return pd.DataFrame(out).round(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None, help="tanggal WIB YYYY-MM-DD")
    a = ap.parse_args()
    pd.set_option("display.width", 220)
    m1 = bt.load_m1("M1")
    bars, tt = bt.Bars(m1), trend_table(m1)
    store = Store(settings.DB_PATH)
    if a.day:
        d0 = datetime.fromisoformat(a.day).replace(tzinfo=timezone.utc) - timedelta(hours=7)
        sigs = bt.load_signals(store, d0, d0 + timedelta(days=1))
        df = evaluate(sigs, bars, tt)
        show = df.copy()
        show["jam"] = (show.time + timedelta(hours=7)).dt.strftime("%H:%M")
        sym = {1: "↑", -1: "↓", 0: "·"}
        for c in rule_cols(df):
            show[c] = show[c].map(lambda x: "searah" if x > 0 else ("LAWAN" if x < 0 else "-"))
        print(f"Sinyal {a.day} (entry market, TP/SL 30). 'searah' = arah sinyal sesuai tren TF itu.")
        print(show[["jam", "sinyal", "hasil", "pips"] + rule_cols(df)].to_string(index=False))
        print()
        print(summarize(df).to_string(index=False))
        return
    sigs = bt.load_signals(store, m1.index[0].to_pydatetime(), m1.index[-1].to_pydatetime())
    df = evaluate(sigs, bars, tt)
    mid = pd.Timestamp("2026-09-24", tz="UTC")
    a1, a2 = summarize(df[df.time < mid]), summarize(df[df.time >= mid])
    res = a1.merge(a2, on="aturan", suffixes=("_Agu-Sep", "_Sep-Nov"))
    res["avg_pips_Agu-Sep"] = (res["pips_Agu-Sep"] / res["trade_Agu-Sep"]).round(2)
    res["avg_pips_Sep-Nov"] = (res["pips_Sep-Nov"] / res["trade_Sep-Nov"]).round(2)
    print("Seluruh data M1 (Agu–Nov 2026), entry market TP/SL 30:")
    print(res[["aturan", "trade_Agu-Sep", "WR%_Agu-Sep", "avg_pips_Agu-Sep", "USD_Agu-Sep",
               "trade_Sep-Nov", "WR%_Sep-Nov", "avg_pips_Sep-Nov", "USD_Sep-Nov"]].to_string(index=False))


if __name__ == "__main__":
    main()
