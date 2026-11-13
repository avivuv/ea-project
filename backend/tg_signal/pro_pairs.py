"""
Uji strategi sendiri (bias EMA50 H1 slope > 0.1 ATR, POI M15, CHoCH M5, entry FVG M5, RR 1:3) di pair lain.

    python -m tg_signal.pro_pairs                      # ambil M5 dari MT5 (cache) lalu backtest
    python -m tg_signal.pro_pairs --no-fetch           # pakai cache saja

Angka dolar strategi (dibuat untuk XAUUSD) diskalakan dengan rasio ATR M5 median pair / XAUUSD:
ukuran POI minimum, buffer SL, dan batas risiko (XAUUSD: 10–100 pips = $1–$10). Hasil dalam R
sehingga bisa dibandingkan antar pair. Latih s/d Maret 2026, uji April–November 2026.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import pandas as pd

from tg_signal import pro_strategy as ps
from tg_signal import settings
from tg_signal.market_data import fetch_from_mt5
from tg_signal.pro_check import line
from tg_signal.pro_live import CFG, EMA_SPAN, BIAS_TF, MIN_SLOPE

SYMBOLS = ["XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "US500", "USTEC", "US30",
           "BTCUSD", "ETHUSD"]
BASE = {"POI_MIN": ps.POI_MIN, "SL_BUF": ps.SL_BUF, "RISK_MIN": ps.RISK_MIN, "RISK_MAX": ps.RISK_MAX}
# Ukuran 1 pip per instrumen (hanya untuk laporan; logika & hasil memakai satuan harga dan R)
PIP = {"XAUUSD": 0.10, "XAGUSD": 0.01, "USDJPY": 0.01, "US500": 1.0, "USTEC": 1.0, "US30": 1.0,
       "BTCUSD": 1.0, "ETHUSD": 0.1}
FX_PIP = 0.0001


def pip_of(sym: str) -> float:
    return PIP.get(sym, FX_PIP)


def cache(sym: str):
    return settings.DATA_DIR / f"m5_{sym}.csv.gz"


def load(sym: str, fetch: bool) -> pd.DataFrame | None:
    p = cache(sym)
    if fetch and sym != "XAUUSD":
        try:
            df = fetch_from_mt5(datetime(2025, 6, 1, tzinfo=timezone.utc),
                                datetime.now(timezone.utc) + timedelta(days=1), symbol=sym, tf="M5")
            if len(df):
                df.to_csv(p, compression="gzip")
        except Exception as e:
            print(f"  {sym}: gagal ambil data ({e})")
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["time"], index_col="time")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def atr_m5(df: pd.DataFrame) -> float:
    return float((df["high"] - df["low"]).median())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    args = ap.parse_args()
    ref = load("XAUUSD", False)
    ref_atr = atr_m5(ref[ref.index >= "2025-06-16"])
    rows = []
    for sym in SYMBOLS:
        df = load(sym, not args.no_fetch)
        if df is None or len(df) < 20000:
            print(f"{sym:<7} data tidak cukup")
            continue
        df = df[df.index >= "2025-06-16"]
        k = atr_m5(df) / ref_atr
        for name, v in BASE.items():
            setattr(ps, name, v * k)
        mk = ps.Market(df, EMA_SPAN, BIAS_TF, MIN_SLOPE)
        t = pd.DataFrame(ps.run_side(mk, CFG, True) + ps.run_side(mk, CFG, False))
        for name, v in BASE.items():
            setattr(ps, name, v)
        if t.empty:
            print(f"{sym:<7} tanpa trade")
            continue
        t = t.sort_values("time")
        m = t.groupby(t.time.dt.strftime("%Y-%m")).R.sum()
        risk_px = t.risk_px                                  # jarak SL dalam satuan harga
        spread_r = float(df["spread"].median() / risk_px.median())
        sl_pips = risk_px.median() / pip_of(sym)
        sl_range = (ps.RISK_MIN * k / pip_of(sym), ps.RISK_MAX * k / pip_of(sym))
        tr, te = ps.stats(t[t.time < ps.SPLIT]), ps.stats(t[t.time >= ps.SPLIT])
        print(f"{sym:<7} {line(t)} | bulan+ {(m > 0).sum()}/{len(m)} | SL median {sl_pips:,.0f} pips "
              f"(batas {sl_range[0]:,.0f}–{sl_range[1]:,.0f}) | spread {spread_r:.2f}R")
        rows.append({"symbol": sym, "skala": k, **{f"tr_{a}": b for a, b in tr.items()},
                     **{f"te_{a}": b for a, b in te.items()}, "bulan_pos": int((m > 0).sum()), "bulan": len(m)})
    pd.DataFrame(rows).to_csv(settings.DATA_DIR / "pro_pairs.csv", index=False)


if __name__ == "__main__":
    main()
