"""
Kenapa trade strategi sendiri (bias EMA50 H1) kena SL? Analisa per ciri saat entry + jalur harga.

    python -m tg_signal.pro_sl_analysis

1. Jalur harga: MFE (seberapa jauh trade sempat untung, dalam R) sebelum SL, dan berapa cepat SL kena.
2. Ciri saat entry dibandingkan antara trade SL dan TP, dipisah latih/uji supaya pola kebetulan terlihat:
   sesi, hari, jarak SL, jenis/umur/ukuran/kesegaran POI, jarak harga ke EMA, kemiringan EMA,
   kesesuaian dengan tren H4, volatilitas, lama menunggu konfirmasi.
3. Alternatif manajemen posisi pada trade yang sama (jalur bar M5): BE, TP parsial, TP lebih dekat.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tg_signal import pro_strategy as ps
from tg_signal import settings
from tg_signal.market_data import load_m1
from tg_signal.pro_live import CFG

PIP = settings.PIP_SIZE


def htf(df: pd.DataFrame, minutes: int, t5: np.ndarray):
    h = df.resample(f"{minutes}min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    k = ps._htf_index(t5, h.index, minutes)
    return h, np.where(k >= 0, k, 0)


def build(df: pd.DataFrame) -> pd.DataFrame:
    mk = ps.Market(df, 50, 60)
    rows = []
    t5 = mk.t
    h1, k1 = htf(df, 60, t5)
    h4, k4 = htf(df, 240, t5)
    ema1 = h1.close.ewm(span=50, adjust=False).mean().to_numpy()
    atr1 = (h1.high - h1.low).rolling(14).mean().to_numpy()
    ema4 = h4.close.ewm(span=50, adjust=False).mean().to_numpy()
    c4 = h4.close.to_numpy()
    atr_med = pd.Series(atr1).rolling(24 * 20, min_periods=50).median().to_numpy()
    for is_buy in (True, False):
        O, H, L, C = mk.arr[is_buy]
        sg = 1 if is_buy else -1
        for tr in ps.run_side(mk, CFG, is_buy):
            e, x, a, pc = tr["entry_i"], tr["exit_i"], tr["arm_i"], tr["poi_created_i"]
            entry, risk = sg * tr["entry"], tr["risk_pips"] * PIP
            path_h = H[e:x] if x > e else H[e:e + 1]
            j1, j4 = k1[e - 1], k4[e - 1]
            top, bot = tr["poi_top"], tr["poi_bottom"]
            rows.append({
                **{k: tr[k] for k in ("time", "dir", "R", "outcome", "risk_pips", "poi", "entry", "sl", "tp")},
                "mfe_R": (path_h.max() - entry) / risk,
                "bars_to_exit": x - e,
                "hour": tr["time"].hour, "dow": tr["time"].day_name()[:3],
                "poi_age_h": (a - pc) * 5 / 60,
                "poi_size": top - bot,
                "poi_fresh": not (L[pc + 1:a] <= top).any(),
                "ema_dist_atr": sg * (C[e - 1] * sg - ema1[j1]) / atr1[j1] if atr1[j1] else np.nan,
                "ema_slope_atr": sg * (ema1[j1] - ema1[max(j1 - 3, 0)]) / atr1[j1] if atr1[j1] else np.nan,
                "h4_agree": bool(sg * (c4[j4] - ema4[j4]) > 0),
                "vol_ratio": atr1[j1] / atr_med[j1] if atr_med[j1] else np.nan,
                "wait_bars": e - a,
                "e": e, "x": x, "is_buy": is_buy,
            })
    d = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
    d["periode"] = np.where(d.time < ps.SPLIT, "latih", "uji")
    d["sl"] = d.R < 0
    return d, mk


def bucket_table(d: pd.DataFrame, col: str, bins=None, labels=None) -> None:
    g = d.copy()
    if bins is not None:
        g[col] = pd.cut(g[col], bins, labels=labels)
    t = g.groupby([col, "periode"], observed=True).agg(n=("R", "size"), sl_pct=("sl", "mean"), avgR=("R", "mean"))
    t["sl_pct"] = (100 * t.sl_pct).round(0)
    t["avgR"] = t.avgR.round(2)
    print(f"\n── {col} ──\n" + t.unstack("periode").to_string())


def manage(d: pd.DataFrame, mk: ps.Market) -> None:
    """Alternatif manajemen di jalur bar M5 yang sama (SL & TP satu bar → SL)."""
    spr = mk.spr

    def walk(row, be=None, part=None, tp=3.0):
        O, H, L, C = mk.arr[row.is_buy]
        entry = (1 if row.is_buy else -1) * row.entry
        risk = row.risk_pips * PIP
        sl, done, half = entry - risk, 0.0, None
        for j in range(row.e, min(mk.n, row.e + 2 * 288 * 5)):
            xadj = 0.0 if row.is_buy else spr[j]
            lo, hi = L[j] - xadj, H[j] - xadj
            if lo <= sl:
                r = (sl - entry) / risk
                return r if half is None else (half + r) / 2
            if part and half is None and hi >= entry + part * risk:
                half, sl = part, max(sl, entry)
            if hi >= entry + tp * risk:
                return tp if half is None else (half + tp) / 2
            if be and hi >= entry + be * risk:
                sl = max(sl, entry)
        return (C[j] - xadj - entry) / risk

    variants = {"DASAR TP3": {}, "TP 2R": {"tp": 2.0}, "BE di +1R": {"be": 1.0}, "BE di +1.5R": {"be": 1.5},
                "BE di +2R": {"be": 2.0}, "parsial 50% di +1R, sisa TP3 (BE)": {"part": 1.0},
                "parsial 50% di +1.5R, sisa TP3 (BE)": {"part": 1.5}}
    print("\n── Alternatif manajemen (trade yang sama) ──")
    for name, kw in variants.items():
        r = d.apply(lambda row: walk(row, **kw), axis=1)
        out = []
        for per in ("latih", "uji"):
            rr = r[d.periode == per]
            eq = rr.cumsum()
            gw, gl = rr[rr > 0].sum(), -rr[rr < 0].sum()
            out.append(f"{per}: R {rr.sum():+6.1f} PF {gw / gl:.2f} DD {float((eq.cummax() - eq).max()):5.1f}")
        print(f"  {name:<38} " + " | ".join(out))


def main() -> None:
    df = load_m1("M5")
    d, mk = build(df)
    d.to_csv(settings.DATA_DIR / "pro_sl_features.csv", index=False)
    sl = d[d.sl]
    print(f"Trade: {len(d)} | SL: {len(sl)} ({100 * len(sl) / len(d):.0f}%) | TP: {(d.R > 0).sum()}")
    print("\n── Jalur harga trade SL ──")
    for x in (0.5, 1.0, 1.5, 2.0, 2.5):
        print(f"  sempat untung ≥ {x}R sebelum SL: {100 * (sl.mfe_R >= x).mean():4.0f}%")
    print(f"  SL dalam ≤ 3 bar M5 (15 mnt): {100 * (sl.bars_to_exit <= 3).mean():.0f}% | "
          f"≤ 12 bar (1 jam): {100 * (sl.bars_to_exit <= 12).mean():.0f}% | median {sl.bars_to_exit.median():.0f} bar")
    print(f"  MFE median trade SL: {sl.mfe_R.median():.2f}R")
    bucket_table(d, "hour", [-1, 6, 11, 16, 23], ["Asia 00-07", "London 07-12", "NY 12-17", "Sore 17-24"])
    bucket_table(d, "dow")
    bucket_table(d, "risk_pips", [0, 30, 45, 60, 80, 100])
    bucket_table(d, "poi")
    bucket_table(d, "poi_fresh")
    bucket_table(d, "poi_age_h", [-1, 6, 24, 48, 80])
    bucket_table(d, "poi_size", [0, 1, 2, 4, 100])
    bucket_table(d, "ema_dist_atr", [-99, 0.5, 1.5, 3, 99])
    bucket_table(d, "ema_slope_atr", [-99, 0.1, 0.3, 0.6, 99])
    bucket_table(d, "h4_agree")
    bucket_table(d, "vol_ratio", [0, 0.8, 1.2, 1.8, 99])
    bucket_table(d, "wait_bars", [-1, 3, 8, 15, 99])
    manage(d, mk)


if __name__ == "__main__":
    main()
