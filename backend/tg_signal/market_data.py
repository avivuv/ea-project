"""
Data harga M1/M5 dari MT5 + cache lokal (data/m1_<SYMBOL>.csv.gz, data/m5_<SYMBOL>.csv.gz).
Catatan: server Exness hanya menyediakan ~100 ribu bar M1 terakhir; M5 tersedia sejak Okt 2025.

    python -m tg_signal.market_data --fetch --start 2025-10-01   # ambil & gabung ke cache
    python -m tg_signal.market_data --info                       # rentang data di cache

Kolom: time (UTC, index), open, high, low, close (harga BID), spread (dalam harga, mis. 0.168).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import pandas as pd

from tg_signal import settings


def _month_ranges(start: datetime, end: datetime):
    cur = start
    while cur < end:
        nxt = datetime(cur.year + (cur.month == 12), cur.month % 12 + 1, 1, tzinfo=timezone.utc)
        yield cur, min(nxt, end)
        cur = nxt


TIMEFRAMES = ("M1", "M5", "M15", "H1", "H4", "D1")


def fetch_from_mt5(start: datetime, end: datetime, symbol: str = settings.SYMBOL,
                   tf: str = "M1") -> pd.DataFrame:
    import MetaTrader5 as mt5  # import lokal: modul lain tetap bisa jalan tanpa MT5

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize gagal: {mt5.last_error()}")
    try:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
        frames = []
        for s, e in _month_ranges(start, end):
            r = mt5.copy_rates_range(symbol, getattr(mt5, f"TIMEFRAME_{tf}"), s, e)
            n = 0 if r is None else len(r)
            print(f"  {s:%Y-%m}: {n} bar")
            if n > 1:
                frames.append(pd.DataFrame(r))
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True) - timedelta(hours=settings.MT5_UTC_OFFSET_H)
        df["spread"] = df["spread"] * info.point
        df = df[["time", "open", "high", "low", "close", "spread"]]
        return df.drop_duplicates("time").set_index("time").sort_index()
    finally:
        mt5.shutdown()


def load_m1(tf: str = "M1") -> pd.DataFrame:
    """Muat cache bar (nama lama dipertahankan; tf = M1 | M5)."""
    p = settings.bars_cache_path(tf)
    if not p.exists():
        raise FileNotFoundError(f"Cache {tf} belum ada: {p}. Jalankan: python -m tg_signal.market_data --fetch --tf {tf}")
    df = pd.read_csv(p, parse_dates=["time"], index_col="time")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def update_cache(start: datetime, end: datetime, tf: str = "M1") -> pd.DataFrame:
    new = fetch_from_mt5(start, end, tf=tf)
    p = settings.bars_cache_path(tf)
    if p.exists():
        new = pd.concat([load_m1(tf), new])
        new = new[~new.index.duplicated(keep="last")].sort_index()
    p.parent.mkdir(parents=True, exist_ok=True)
    new.to_csv(p, compression="gzip")
    return new


def _info(df: pd.DataFrame) -> None:
    print(f"Bar: {len(df)} | {df.index[0]} → {df.index[-1]}")
    print(f"Spread median: {df['spread'].median():.3f} (= {df['spread'].median() / settings.PIP_SIZE:.1f} pips)")
    per_month = df.groupby(df.index.strftime("%Y-%m")).size()
    print(per_month.to_string())


def main() -> None:
    ap = argparse.ArgumentParser(description="Data M1 XAUUSD dari MT5")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--info", action="store_true")
    ap.add_argument("--start", default="2025-10-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--tf", default="M1", choices=TIMEFRAMES)
    args = ap.parse_args()
    if args.fetch:
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        end = (datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
               if args.end else datetime.now(timezone.utc) + timedelta(days=1))
        _info(update_cache(start, end, args.tf))
    elif args.info:
        _info(load_m1(args.tf))


if __name__ == "__main__":
    main()
