"""
Unduh candle M1 XAUUSD (BID) dari datafeed publik Dukascopy → cache per tahun.

    python -m intraday.dukascopy --years 2019 2020 2021 2022 2023 2024 2025
    python -m intraday.dukascopy --info

File sumber: https://datafeed.dukascopy.com/datafeed/XAUUSD/{YYYY}/{MM-1:02}/{DD}/BID_candles_min_1.bi5
(LZMA, record 24 byte big-endian: detik sejak 00:00 UTC, open, close, low, high [×1/1000], volume float).
Waktu UTC. Spread tidak tersedia di file BID → backtest memakai spread tetap (lihat SPREAD).
Hasil: tg_signal/data/dukascopy/XAUUSD_M1_{YYYY}.csv.gz (gitignored).
"""
from __future__ import annotations

import argparse
import lzma
import struct
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from tg_signal import settings

OUT_DIR = settings.DATA_DIR / "dukascopy"
URL = "https://datafeed.dukascopy.com/datafeed/XAUUSD/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
SCALE = 1000.0
SPREAD = 0.25            # $ — asumsi konservatif (median Exness 0.168)
REC = struct.Struct(">IIIIIf")


def fetch_day(day: date) -> pd.DataFrame | None:
    url = URL.format(y=day.year, m=day.month - 1, d=day.day)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (data-research)"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"gagal unduh {url}")
    if not raw:
        return None
    data = lzma.decompress(raw, format=lzma.FORMAT_ALONE)
    rows = [REC.unpack_from(data, i) for i in range(0, len(data) - len(data) % REC.size, REC.size)]
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["sec", "open", "close", "low", "high", "volume"])
    df = df[df["volume"] > 0]                      # menit tanpa transaksi (pasar tutup) dibuang
    if df.empty:
        return None
    base = pd.Timestamp(day, tz="UTC")
    df["time"] = base + pd.to_timedelta(df["sec"], unit="s")
    for k in ("open", "close", "low", "high"):
        df[k] = df[k] / SCALE
    return df[["time", "open", "high", "low", "close", "volume"]]


def download_year(year: int, workers: int = 8) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"XAUUSD_M1_{year}.csv.gz"
    if out.exists():
        print(f"{year}: sudah ada ({out.name})")
        return out
    days = [date(year, 1, 1) + timedelta(d) for d in range((date(year + 1, 1, 1) - date(year, 1, 1)).days)]
    days = [d for d in days if d.weekday() != 5]   # Sabtu selalu tutup
    with ThreadPoolExecutor(workers) as ex:
        frames = [f for f in ex.map(fetch_day, days) if f is not None]
    df = pd.concat(frames).drop_duplicates("time").sort_values("time")
    df.to_csv(out, index=False, compression="gzip")
    print(f"{year}: {len(df)} bar M1, {df.time.dt.date.nunique()} hari, harga {df.close.iloc[0]:.0f} → {df.close.iloc[-1]:.0f}")
    return out


def load(years: list[int] | None = None, tf: str = "M1") -> pd.DataFrame:
    files = sorted(OUT_DIR.glob("XAUUSD_M1_*.csv.gz"))
    if years:
        files = [f for f in files if int(f.stem.split("_")[-1].split(".")[0]) in years]
    df = pd.concat(pd.read_csv(f, parse_dates=["time"]) for f in files).set_index("time").sort_index()
    df["spread"] = SPREAD
    if tf != "M1":
        mins = int(tf[1:])
        df = df.resample(f"{mins}min", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "spread": "first"}).dropna()
    return df[["open", "high", "low", "close", "spread"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="*", default=[])
    ap.add_argument("--info", action="store_true")
    a = ap.parse_args()
    for y in a.years:
        download_year(y)
    if a.info:
        for f in sorted(OUT_DIR.glob("*.csv.gz")):
            print(f.name, f.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
