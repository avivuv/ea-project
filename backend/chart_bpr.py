"""
Visualisasi sample BPR (Balanced Price Range) dari data XAUUSD M15.

Scan seluruh dataset, temukan semua zona BPR yang pernah terbentuk,
lalu generate chart PNG untuk setiap zona dengan markup:
  - Candlestick M15
  - Bull FVG  (hijau transparan) + tandai candle C1/C2/C3-nya
  - Bear FVG  (merah transparan) + tandai candle C1/C2/C3-nya
  - BPR overlap zone (kuning/emas, border tebal)
  - BPR midpoint (garis biru putus-putus)
  - Entry / SL / TP jika harga menyentuh zona

python chart_bpr.py
Output: backend/charts/bpr_*.png
"""
from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import ta

from bpr_detector import detect_bpr, BPRZone
from config import ATR_PERIOD, BPR_RR, BPR_SL_BUFFER_ATR

# ── Tunable ──────────────────────────────────────────────────────────────────
LOOKBACK          = 150   # bar M15 untuk scan BPR (≈37 jam)
GAP_ATR           = 0.15  # minimum FVG size (× ATR) — cukup longgar agar dapat sample
DISP_RATIO        = 0.30  # minimum body/range C2 — longgar
MAX_TEMPORAL_GAP  = 24    # jarak max bars antar dua FVG (ICT V-shape, ≈6 jam M15)
STEP       = 4       # scan tiap N bar (tiap jam)
WARMUP     = 250     # bar warmup untuk ATR stabil
CHART_PRE  = 60      # bar sebelum BPR zone tampil di chart
CHART_POST = 60      # bar sesudah BPR zone deteksi
DEDUP_DIST = 8.0     # USD — zona dengan mid berjarak < ini dianggap duplikat
MAX_CHARTS = 20      # maksimum chart yang dihasilkan


def load_csv(path: str) -> pd.DataFrame:
    with open(path) as f:
        first = f.readline().strip()
    is_mt5 = first.split(",")[0].strip()[:4].isdigit()
    if is_mt5:
        df = pd.read_csv(path, header=None,
                         names=["date","time_col","open","high","low","close","volume"])
        df["time"] = pd.to_datetime(df["date"]+" "+df["time_col"],
                                    format="%Y.%m.%d %H:%M:%S")
        df = df.drop(columns=["date","time_col"])
    else:
        df = pd.read_csv(path, parse_dates=["time"])
        df.columns = [c.lower() for c in df.columns]
    return df.sort_values("time").reset_index(drop=True)


def draw_candles(ax, df_win: pd.DataFrame) -> None:
    """Gambar candlestick sederhana pada axes ax."""
    xs = np.arange(len(df_win))
    for xi, (_, row) in zip(xs, df_win.iterrows()):
        op, cl, hi, lo = row["open"], row["close"], row["high"], row["low"]
        bullish = cl >= op
        color   = "#26a69a" if bullish else "#ef5350"
        edge    = "#00897b" if bullish else "#c62828"
        body_lo = min(op, cl)
        body_hi = max(op, cl)
        # Body
        ax.add_patch(mpatches.FancyBboxPatch(
            (xi - 0.35, body_lo), 0.70, max(body_hi - body_lo, 0.001),
            boxstyle="square,pad=0",
            facecolor=color, edgecolor=edge, linewidth=0.6, zorder=3
        ))
        # Wick
        ax.plot([xi, xi], [lo, hi], color=edge, linewidth=0.8, zorder=2)


def fvg_candle_indices(bars_ago: int, det_local: int) -> tuple[int, int, int]:
    """
    Kembalikan indeks lokal (dalam df_win) dari candle C1, C2, C3 FVG.
    bars_ago  = jarak C3 dari bar deteksi di dalam slice WARMUP-bar.
    det_local = posisi bar deteksi di dalam df_win.
    """
    c3_local = det_local - bars_ago
    return c3_local - 2, c3_local - 1, c3_local   # C1, C2, C3


def plot_bpr(
    df_full: pd.DataFrame,
    found_idx: int,       # index di df_full saat zona terdeteksi
    zone: BPRZone,
    atr: float,
    chart_idx: int,
    out_dir: str,
) -> str:
    older = max(zone.bull_fvg.bars_ago, zone.bear_fvg.bars_ago)
    start = max(0, found_idx - older - CHART_PRE)
    end   = min(len(df_full), found_idx + CHART_POST + 1)
    df_win = df_full.iloc[start:end].reset_index(drop=True)

    # Indeks "detection point" dalam df_win
    det_local = found_idx - start

    # ── Setup figure ─────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(18, 9))
    fig.patch.set_facecolor("#131722")
    ax.set_facecolor("#131722")

    draw_candles(ax, df_win)

    price_lo = df_win["low"].min()
    price_hi = df_win["high"].max()
    pad      = (price_hi - price_lo) * 0.08
    ax.set_ylim(price_lo - pad, price_hi + pad)
    ax.set_xlim(-1, len(df_win))

    # ── Shading FVG dan BPR ───────────────────────────────────────────────────
    # Bull FVG (hijau transparan)
    ax.axhspan(zone.bull_fvg.bottom, zone.bull_fvg.top,
               color="#00e676", alpha=0.12, zorder=1, label="Bull FVG")
    ax.axhline(zone.bull_fvg.mid, color="#00e676", linewidth=0.6,
               linestyle=":", alpha=0.6)

    # Bear FVG (merah transparan)
    ax.axhspan(zone.bear_fvg.bottom, zone.bear_fvg.top,
               color="#ff1744", alpha=0.12, zorder=1, label="Bear FVG")
    ax.axhline(zone.bear_fvg.mid, color="#ff1744", linewidth=0.6,
               linestyle=":", alpha=0.6)

    # BPR overlap zone (kuning, lebih solid + border)
    bpr_rect = mpatches.Rectangle(
        (0, zone.bottom), len(df_win), zone.top - zone.bottom,
        facecolor="#ffd600", alpha=0.25, edgecolor="#ffd600",
        linewidth=1.5, linestyle="--", zorder=2, label="BPR overlap"
    )
    ax.add_patch(bpr_rect)

    # BPR midpoint
    ax.axhline(zone.mid, color="#ffd600", linewidth=1.2,
               linestyle="--", alpha=0.9, label="BPR mid", zorder=4)

    # Label zona
    ax.text(1, zone.top + atr * 0.05,
            f"BPR top: {zone.top:.2f}", color="#ffd600", fontsize=8, zorder=5)
    ax.text(1, zone.bottom - atr * 0.18,
            f"BPR bot: {zone.bottom:.2f}", color="#ffd600", fontsize=8, zorder=5)
    ax.text(1, zone.mid + atr * 0.03,
            f"mid: {zone.mid:.2f}", color="#ffd600", fontsize=8, zorder=5, style="italic")

    # ── Tandai candle pembentuk setiap FVG ────────────────────────────────────
    total_bars = len(df_win)

    def mark_fvg_candles(fvg, color: str, label_prefix: str):
        c1_l, c2_l, c3_l = fvg_candle_indices(fvg.bars_ago, det_local)
        for ci, cn in [(c1_l, "C1"), (c2_l, "C2"), (c3_l, "C3")]:
            if 0 <= ci < total_bars:
                row = df_win.iloc[ci]
                y_pos = row["low"] - atr * 0.4
                ax.text(ci, y_pos, f"{label_prefix}\n{cn}",
                        ha="center", va="top", fontsize=6.5,
                        color=color, fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.2", facecolor="#131722",
                                  edgecolor=color, alpha=0.8))

    mark_fvg_candles(zone.bull_fvg, "#00e676", "Bull")
    mark_fvg_candles(zone.bear_fvg, "#ff5252", "Bear")

    # ── Garis deteksi ────────────────────────────────────────────────────────
    ax.axvline(det_local, color="#ffffff", linewidth=0.8,
               linestyle=":", alpha=0.5, label="Deteksi")
    ax.text(det_local + 0.5, price_hi + pad * 0.3,
            "← deteksi", color="#aaaaaa", fontsize=8, va="top")

    # ── Entry / SL / TP (simulasi jika bounce terjadi setelah deteksi) ───────
    sl_buf  = BPR_SL_BUFFER_ATR * atr
    zone_sz = zone.top - zone.bottom
    sl_dist = zone_sz / 2.0 + sl_buf   # mode LIMIT entry di mid
    tp_dist = sl_dist * BPR_RR

    if zone.direction == "BUY":
        entry = zone.mid
        sl    = zone.bottom - sl_buf
        tp    = entry + tp_dist
        clr   = "#26a69a"
        dir_sym = "▲ BUY"
    else:
        entry = zone.mid
        sl    = zone.top + sl_buf
        tp    = entry - tp_dist
        clr   = "#ef5350"
        dir_sym = "▼ SELL"

    ax.axhline(entry, color=clr,    linewidth=1.0, linestyle="-.",  alpha=0.8, label=f"Entry {entry:.2f}")
    ax.axhline(sl,    color="#ff1744", linewidth=1.0, linestyle="--", alpha=0.7, label=f"SL {sl:.2f}")
    ax.axhline(tp,    color="#00e676", linewidth=1.0, linestyle="--", alpha=0.7, label=f"TP {tp:.2f}")

    ax.text(len(df_win) - 1, entry, f" Entry {entry:.2f}", color=clr,       fontsize=7.5, va="center")
    ax.text(len(df_win) - 1, sl,    f" SL {sl:.2f}",       color="#ff5252", fontsize=7.5, va="center")
    ax.text(len(df_win) - 1, tp,    f" TP {tp:.2f}",       color="#69f0ae", fontsize=7.5, va="center")

    # ── X-axis labels (waktu tiap 12 bar ≈ 3 jam) ────────────────────────────
    tick_step = max(1, len(df_win) // 12)
    ticks = list(range(0, len(df_win), tick_step))
    ax.set_xticks(ticks)
    ax.set_xticklabels(
        [df_win["time"].iloc[t].strftime("%m/%d %H:%M") for t in ticks],
        rotation=30, ha="right", fontsize=7, color="#cccccc"
    )
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.tick_params(axis="y", colors="#cccccc", labelsize=8)
    ax.tick_params(axis="x", colors="#cccccc")
    for spine in ax.spines.values():
        spine.set_edgecolor("#333333")
    ax.grid(axis="y", color="#333333", linewidth=0.5, linestyle="--", alpha=0.5)

    # ── Title & Legend ────────────────────────────────────────────────────────
    overlap_size = zone.top - zone.bottom
    title = (
        f"BPR Sample #{chart_idx}  |  XAUUSD M15  |  Arah: {dir_sym}\n"
        f"BPR zone: [{zone.bottom:.2f} – {zone.top:.2f}]  overlap={overlap_size:.2f}  "
        f"mid={zone.mid:.2f}  |  "
        f"Bull FVG [{zone.bull_fvg.bottom:.2f}–{zone.bull_fvg.top:.2f}] {zone.bull_fvg.bars_ago}b ago  |  "
        f"Bear FVG [{zone.bear_fvg.bottom:.2f}–{zone.bear_fvg.top:.2f}] {zone.bear_fvg.bars_ago}b ago  |  "
        f"RR 1:{BPR_RR:.0f}"
    )
    ax.set_title(title, color="#ffffff", fontsize=9, pad=10, loc="left",
                 fontfamily="monospace")

    legend_patches = [
        mpatches.Patch(facecolor="#00e676", alpha=0.4, label="Bull FVG"),
        mpatches.Patch(facecolor="#ff1744", alpha=0.4, label="Bear FVG"),
        mpatches.Patch(facecolor="#ffd600", alpha=0.4, label="BPR overlap"),
        mpatches.Patch(facecolor=clr,       alpha=0.7, label=f"Entry ({dir_sym})"),
        mpatches.Patch(facecolor="#ff1744", alpha=0.7, label="Stop Loss"),
        mpatches.Patch(facecolor="#00e676", alpha=0.7, label="Take Profit"),
    ]
    ax.legend(handles=legend_patches, loc="upper left",
              facecolor="#1e222d", edgecolor="#333333",
              labelcolor="#dddddd", fontsize=8, ncol=3)

    plt.tight_layout()
    fname = os.path.join(out_dir, f"bpr_{chart_idx:02d}_{df_win['time'].iloc[det_local].strftime('%Y%m%d_%H%M')}_{zone.direction}.png")
    plt.savefig(fname, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return fname


def main():
    base = os.path.dirname(__file__)
    csv  = os.path.join(base, "..", "data", "XAUUSD_GMT+0_NO-DST_M15.csv")
    if not os.path.exists(csv):
        print("CSV tidak ditemukan."); sys.exit(1)

    out_dir = os.path.join(base, "charts")
    os.makedirs(out_dir, exist_ok=True)

    print(f"Memuat data...")
    df = load_csv(csv)
    print(f"  {len(df):,} candle | {df['time'].iloc[0]} s/d {df['time'].iloc[-1]}")
    print(f"  Scan setiap {STEP} bar | LOOKBACK={LOOKBACK} | GAP>={GAP_ATR}xATR | DISP>={DISP_RATIO}\n")

    found: list[tuple[int, BPRZone, float]] = []  # (full_idx, zone, atr)
    t0 = time.time()

    for i in range(WARMUP, len(df), STEP):
        sl = df.iloc[max(0, i - WARMUP + 1): i + 1].copy()
        sl["atr"] = ta.volatility.average_true_range(
            sl["high"], sl["low"], sl["close"], window=ATR_PERIOD
        )
        atr = sl["atr"].iloc[-1]
        if pd.isna(atr) or atr <= 0:
            continue

        min_gap = GAP_ATR * atr
        zones   = detect_bpr(sl, lookback=LOOKBACK, min_gap=min_gap,
                              displacement_ratio=DISP_RATIO,
                              max_temporal_gap=MAX_TEMPORAL_GAP)

        for z in zones:
            # Dedup: lewati zona dengan mid serupa yang sudah tercatat
            duplicate = any(abs(z.mid - prev_z.mid) < DEDUP_DIST for _, prev_z, _ in found)
            if not duplicate:
                found.append((i, z, float(atr)))
                print(f"  [{len(found):>2}] bar={i:,}  {df['time'].iloc[i].strftime('%Y-%m-%d %H:%M')}  "
                      f"dir={z.direction:<5}  zone=[{z.bottom:.2f}–{z.top:.2f}]  "
                      f"bull_ago={z.bull_fvg.bars_ago} bear_ago={z.bear_fvg.bars_ago}  "
                      f"atr={atr:.2f}")

        if len(found) >= MAX_CHARTS:
            break

        if (i - WARMUP) % 1000 == 0:
            pct = (i - WARMUP) / (len(df) - WARMUP) * 100
            print(f"  Scan {pct:.0f}% ... zona={len(found)}", end="\r")

    elapsed = time.time() - t0
    print(f"\nSelesai scan {elapsed:.1f}s | {len(found)} zona BPR unik ditemukan\n")

    if not found:
        print("Tidak ada zona BPR ditemukan. Coba turunkan GAP_ATR atau DISP_RATIO.")
        return

    # Simpan metadata zona ke JSON (untuk re-run chart tanpa rescan)
    meta_path = os.path.join(out_dir, "bpr_zones_meta.json")
    import json
    with open(meta_path, "w") as mf:
        json.dump([{
            "full_idx": fi,
            "direction": z.direction,
            "top": z.top, "bottom": z.bottom, "mid": z.mid,
            "bull_fvg": {"top": z.bull_fvg.top, "bottom": z.bull_fvg.bottom,
                         "mid": z.bull_fvg.mid, "bars_ago": z.bull_fvg.bars_ago},
            "bear_fvg": {"top": z.bear_fvg.top, "bottom": z.bear_fvg.bottom,
                         "mid": z.bear_fvg.mid, "bars_ago": z.bear_fvg.bars_ago},
            "newer_bars_ago": z.newer_bars_ago,
            "quality": z.quality, "atr": a,
            "time": df["time"].iloc[fi].strftime("%Y-%m-%d %H:%M"),
        } for fi, z, a in found], mf, indent=2)
    print(f"  Zona tersimpan: {meta_path}\n")

    print(f"Membuat {len(found)} chart...\n")
    for ci, (full_idx, zone, atr) in enumerate(found, 1):
        fname = plot_bpr(df, full_idx, zone, atr, ci, out_dir)
        print(f"  [{ci:>2}/{len(found)}] {os.path.basename(fname)}")

    print(f"\nChart tersimpan di: {out_dir}")


if __name__ == "__main__":
    main()
