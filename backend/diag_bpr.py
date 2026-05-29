"""
Diagnostik BPR: hitung berapa banyak BPR zone yang terbentuk di XAUUSD M15.
Scan seluruh dataset, ambil sampling tiap N bar, print distribusi.

python diag_bpr.py
"""
from __future__ import annotations
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import ta
from bpr_detector import detect_bpr, find_nearest_bpr
from config import ATR_PERIOD

PAIR    = "XAUUSD"
WARMUP  = 250
STEP    = 16   # sample tiap 4 jam M15 — cukup untuk gambaran umum

def load_csv(path: str) -> pd.DataFrame:
    with open(path) as f:
        first = f.readline().strip()
    is_mt5 = first.split(",")[0].strip()[:4].isdigit()
    if is_mt5:
        df = pd.read_csv(path, header=None,
                         names=["date","time_col","open","high","low","close","volume"])
        df["time"] = pd.to_datetime(df["date"]+" "+df["time_col"], format="%Y.%m.%d %H:%M:%S")
        df = df.drop(columns=["date","time_col"])
    else:
        df = pd.read_csv(path, parse_dates=["time"])
        df.columns = [c.lower() for c in df.columns]
    return df.sort_values("time").reset_index(drop=True)

def main():
    base = os.path.dirname(__file__)
    csv  = os.path.join(base, "..", "data", "XAUUSD_GMT+0_NO-DST_M15.csv")
    if not os.path.exists(csv):
        print("CSV tidak ditemukan"); sys.exit(1)

    df = load_csv(csv)
    print(f"Data: {len(df):,} candle | {df['time'].iloc[0]} s/d {df['time'].iloc[-1]}\n")

    # ── Parameter matrix untuk di-test ───────────────────────────────────────
    configs = [
        dict(lookback=100, gap=0.30, disp=0.5, temporal=24, label="default     "),
        dict(lookback=100, gap=0.20, disp=0.4, temporal=32, label="relax gap   "),
        dict(lookback=150, gap=0.15, disp=0.3, temporal=48, label="relax all   "),
        dict(lookback=200, gap=0.10, disp=0.2, temporal=96, label="extreme     "),
    ]

    for cfg in configs:
        zone_counts   = []
        prox_hit_any  = 0
        total_samples = 0
        t0 = time.time()

        for i in range(WARMUP, len(df), STEP):
            sl = df.iloc[max(0, i - WARMUP + 1): i + 1].copy()
            sl["atr"] = ta.volatility.average_true_range(
                sl["high"], sl["low"], sl["close"], window=ATR_PERIOD
            )
            atr = sl["atr"].iloc[-1]
            if pd.isna(atr) or atr <= 0:
                continue

            min_gap = cfg["gap"] * atr
            zones   = detect_bpr(sl, lookback=cfg["lookback"],
                                 min_gap=min_gap,
                                 displacement_ratio=cfg["disp"],
                                 max_temporal_gap=cfg["temporal"])
            zone_counts.append(len(zones))
            total_samples += 1

            # Cek apakah harga dekat zona mana pun (proximity 3×ATR)
            curr = sl["close"].iloc[-1]
            for z in zones:
                if z.direction == "BUY":
                    dist = max(0, curr - z.top)
                else:
                    dist = max(0, z.bottom - curr)
                if dist <= 3.0 * atr:
                    prox_hit_any += 1
                    break

        if not zone_counts:
            print(f"  {cfg['label']} — tidak ada data"); continue

        avg_zones  = sum(zone_counts) / len(zone_counts)
        has_zone   = sum(1 for c in zone_counts if c > 0)
        prox_pct   = prox_hit_any / total_samples * 100
        max_zones  = max(zone_counts)

        elapsed = time.time() - t0
        print(f"  {cfg['label']} lb={cfg['lookback']} gap={cfg['gap']} disp={cfg['disp']}")
        print(f"    Samples: {total_samples:,} | Avg zones/sample: {avg_zones:.2f} | "
              f"Max zones: {max_zones} | Samples dgn >=1 zona: {has_zone} ({has_zone/total_samples*100:.1f}%)")
        print(f"    Price dekat zona (3×ATR): {prox_hit_any} ({prox_pct:.1f}%) | "
              f"Waktu: {elapsed:.1f}s\n")

if __name__ == "__main__":
    main()
