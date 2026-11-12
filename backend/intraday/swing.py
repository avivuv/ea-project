"""
Backtest swing / trend-following XAUUSD di bar H1 Exness (2014 – 2026), hasil dalam R.

    python -m intraday.swing                 # semua variasi, ringkasan latih/uji + per tahun
    python -m intraday.swing --detail NAME   # rincian satu variasi (long/short, per tahun)

Aturan umum (sama untuk semua strategi, ditetapkan sebelum melihat hasil):
- Sinyal dari bar TF (H1/H4/D1, di-resample dari H1) yang SUDAH close; entry di open bar H1 berikutnya.
- Data harga = BID. BUY masuk di ask (open + spread), SELL keluar di ask. Spread per bar asli,
  minimum 2 pips, + slippage 0,5 pip per sisi.
- SL = k × ATR(14) TF sinyal. Exit: TP kelipatan R, atau trailing chandelier (ekstrem sejak entry − m × ATR),
  atau batas waktu. SL & TP di bar yang sama → dihitung SL. Trailing diperbarui setelah bar close.
- 1 posisi per strategi. Swap tidak dihitung (lihat rata-rata lama hold).
- Latih 2014–2019, uji 2020–2026.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal.market_data import load_m1

PIP = 0.1
MIN_SPREAD = 0.2
SLIP = 0.05
SPLIT = pd.Timestamp("2020-01-01", tz="UTC")
RULES = {"H1": "1h", "H4": "4h", "D1": "1D"}


# ── Data ────────────────────────────────────────────────────────────────────
def load_h1(symbol: str = "XAUUSD") -> pd.DataFrame:
    """XAUUSD dari cache utama; simbol lain dari data/h1_<SYMBOL>.csv.gz. Biaya diskalakan per simbol."""
    global MIN_SPREAD, SLIP
    if symbol == "XAUUSD":
        df = load_m1("H1")
        MIN_SPREAD, SLIP = 0.2, 0.05
    else:
        df = pd.read_csv(settings.DATA_DIR / f"h1_{symbol}.csv.gz", parse_dates=["time"], index_col="time")
        med = df["spread"].replace(0, np.nan).median()
        MIN_SPREAD, SLIP = 1.2 * med, 0.3 * med      # konservatif: spread ≥ 1,2× median, slip 0,3× median
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def resample(h1: pd.DataFrame, tf: str) -> pd.DataFrame:
    if tf == "H1":
        return h1.copy()
    return h1.resample(RULES[tf], label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


# ── Variasi ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class V:
    strat: str           # DONCHIAN | PULLBACK | NR7 | EMACROSS
    tf: str              # TF sinyal
    n: int               # periode channel / EMA cepat
    sl_atr: float        # SL = sl_atr × ATR
    exit: str            # "2R" | "3R" | "trail3" ...
    trend: str = "-"     # filter tren: "-" | "D1" (close D1 vs EMA200 D1) | "EMA" (EMA50 vs EMA200 TF sinyal)

    @property
    def name(self) -> str:
        return f"{self.strat}_{self.tf}_n{self.n}_SL{self.sl_atr:g}ATR_{self.exit}_tr{self.trend}"


def signals(h1: pd.DataFrame, v: V, d1_trend: pd.Series) -> pd.DataFrame:
    """Kembalikan DataFrame index = waktu CLOSE bar TF, kolom dir (+1/−1), sl_dist (harga)."""
    b = resample(h1, v.tf)
    a = atr(b)
    c = b["close"]
    if v.strat == "DONCHIAN":       # close menembus high/low n bar sebelumnya
        hi, lo = b.high.rolling(v.n).max().shift(1), b.low.rolling(v.n).min().shift(1)
        d = np.where(c > hi, 1, np.where(c < lo, -1, 0))
    elif v.strat == "PULLBACK":     # tren EMA50/200, RSI(14) keluar dari zona pullback (40/60)
        up = ema(c, 50) > ema(c, 200)
        r = rsi(c)
        d = np.where(up & (r.shift(1) < 40) & (r >= 40), 1,
                     np.where(~up & (r.shift(1) > 60) & (r <= 60), -1, 0))
    elif v.strat == "NR7":          # bar tersempit dari 7 → order stop di high/low bar itu (bar berikutnya)
        rng = b.high - b.low
        nr = rng <= rng.rolling(7).min()
        hi, lo = b.high.shift(1), b.low.shift(1)
        nrp = nr.shift(1, fill_value=False)
        brk_up, brk_dn = nrp & (b.high > hi), nrp & (b.low < lo)
        d = np.where(brk_up & ~brk_dn & (c > hi), 1, np.where(brk_dn & ~brk_up & (c < lo), -1, 0))
    elif v.strat == "EMACROSS":     # EMA n vs EMA 4n cross
        f, s = ema(c, v.n), ema(c, 4 * v.n)
        x = np.sign(f - s)
        d = np.where((x > 0) & (x.shift(1) <= 0), 1, np.where((x < 0) & (x.shift(1) >= 0), -1, 0))
    else:
        raise ValueError(v.strat)
    close_t = b.index + pd.Timedelta(RULES[v.tf])
    out = pd.DataFrame({"dir": d, "sl_dist": v.sl_atr * a.to_numpy()}, index=close_t)
    out = out[(out.dir != 0) & out.sl_dist.notna()]
    if v.trend == "D1":
        t = d1_trend.reindex(out.index, method="ffill").fillna(0).to_numpy()
        out = out[out.dir.to_numpy() == t]
    elif v.trend == "EMA":
        tr = np.sign(ema(c, 50) - ema(c, 200))
        tr.index = close_t
        out = out[out.dir.to_numpy() == tr.reindex(out.index).to_numpy()]
    return out


def d1_trend_series(h1: pd.DataFrame) -> pd.Series:
    d = resample(h1, "D1")
    tr = np.sign(d.close - ema(d.close, 200))
    tr.index = d.index + pd.Timedelta("1D")      # berlaku setelah bar D1 close
    return tr


# ── Simulasi di bar H1 ──────────────────────────────────────────────────────
def simulate(h1: pd.DataFrame, sig: pd.DataFrame, v: V) -> pd.DataFrame:
    t = h1.index.values
    o, h, l, c = (h1[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    spr = np.maximum(h1["spread"].to_numpy(float), MIN_SPREAD)
    idx = np.searchsorted(t, sig.index.values.astype("datetime64[ns]"), side="left")
    tp_r = float(v.exit[:-1]) if v.exit.endswith("R") else None
    trail_m = float(v.exit[5:]) if v.exit.startswith("trail") else None
    max_bars = 24 * 60
    rows, free_at = [], 0
    for i, dr, sl_dist in zip(idx, sig.dir.to_numpy(), sig.sl_dist.to_numpy()):
        if i >= len(t) or i < free_at or sl_dist <= 0:
            continue
        trail = trail_m / v.sl_atr * sl_dist if trail_m else None   # trail dalam harga (ATR saat entry)
        if dr > 0:
            entry = o[i] + spr[i] + SLIP
            sl, tp, ext = entry - sl_dist, (entry + tp_r * sl_dist if tp_r else np.inf), h[i]
        else:
            entry = o[i] - SLIP
            sl, tp, ext = entry + sl_dist, (entry - tp_r * sl_dist if tp_r else -np.inf), l[i]
        end = min(len(t), i + max_bars)
        exit_p, j, why = None, i, "TIME"
        for j in range(i, end):
            if dr > 0:
                if l[j] <= sl:
                    exit_p, why = min(sl, o[j]) - SLIP, "SL"; break
                if h[j] >= tp:
                    exit_p, why = max(tp, o[j]) - SLIP, "TP"; break
                if trail:
                    ext = max(ext, h[j]); sl = max(sl, ext - trail)
            else:
                ah, al, ao = h[j] + spr[j], l[j] + spr[j], o[j] + spr[j]
                if ah >= sl:
                    exit_p, why = max(sl, ao) + SLIP, "SL"; break
                if al <= tp:
                    exit_p, why = min(tp, ao) + SLIP, "TP"; break
                if trail:
                    ext = min(ext, l[j]); sl = min(sl, ext + trail)
        if exit_p is None:
            exit_p = c[j] - SLIP if dr > 0 else c[j] + spr[j] + SLIP
        pnl = (exit_p - entry) if dr > 0 else (entry - exit_p)
        rows.append({"time": pd.Timestamp(t[i], tz="UTC"), "dir": int(dr), "r": pnl / sl_dist,
                     "why": why, "hold_h": j - i + 1, "risk_pips": sl_dist / PIP})
        free_at = j + 1
    return pd.DataFrame(rows)


def stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"n": 0, "WR%": 0, "avgR": 0, "totR": 0, "PF": 0, "DD_R": 0}
    r = tr["r"].to_numpy()
    eq = np.cumsum(r)
    gw, gl = r[r > 0].sum(), -r[r < 0].sum()
    return {"n": len(r), "WR%": round(100 * (r > 0).mean()), "avgR": round(r.mean(), 3),
            "totR": round(r.sum(), 1), "PF": round(gw / gl, 2) if gl else np.inf,
            "DD_R": round((np.maximum.accumulate(eq) - eq).max(), 1)}


def variants() -> list[V]:
    vs = []
    for tf, ns in (("D1", (20, 55)), ("H4", (20, 55))):
        for n in ns:
            for ex in ("2R", "3R", "trail3", "trail4"):
                for trd in ("-", "D1"):
                    vs.append(V("DONCHIAN", tf, n, 2, ex, trd))
    for tf in ("H1", "H4"):
        for sl in (1.5, 2):
            for ex in ("2R", "3R", "trail3"):
                vs.append(V("PULLBACK", tf, 0, sl, ex, "-"))
                vs.append(V("PULLBACK", tf, 0, sl, ex, "D1"))
    for tf in ("H4", "D1"):
        for ex in ("2R", "3R", "trail3"):
            for trd in ("-", "D1"):
                vs.append(V("NR7", tf, 7, 1, ex, trd))
    for tf, n in (("H4", 20), ("D1", 10), ("D1", 20)):
        for ex in ("3R", "trail3", "trail4"):
            vs.append(V("EMACROSS", tf, n, 2, ex, "-"))
    return vs


def run(h1: pd.DataFrame, v: V, d1t: pd.Series) -> pd.DataFrame:
    return simulate(h1, signals(h1, v, d1t), v)


def null_test(h1: pd.DataFrame, v: V, d1t: pd.Series, runs: int = 200, seed: int = 0) -> dict:
    """Entry acak: jumlah & arah sinyal sama, waktu diacak (jam & SL-ATR ikut dari bar acak)."""
    sig = signals(h1, v, d1t)
    real = simulate(h1, sig, v)
    b = resample(h1, v.tf)
    a = (v.sl_atr * atr(b)).dropna()
    close_t = a.index + pd.Timedelta(RULES[v.tf])
    if v.trend == "D1":     # acak tetap searah filter tren (supaya adil)
        tr = d1t.reindex(close_t, method="ffill").fillna(0).to_numpy()
    rng = np.random.default_rng(seed)
    avg = []
    for _ in range(runs):
        dirs = rng.choice(sig.dir.to_numpy(), size=len(sig))
        pos = np.sort(rng.choice(len(close_t), size=len(sig), replace=False))
        d = tr[pos] if v.trend == "D1" else dirs
        keep = d != 0
        s = pd.DataFrame({"dir": d[keep], "sl_dist": a.to_numpy()[pos][keep]}, index=close_t[pos][keep])
        r = simulate(h1, s, v)
        avg.append(r.r.mean() if len(r) else 0)
    avg = np.array(avg)
    return {"real_avgR": round(real.r.mean(), 3), "acak_avgR": round(avg.mean(), 3),
            "persentil": round(100 * (avg < real.r.mean()).mean())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", default=None)
    ap.add_argument("--null", nargs="*", default=None, help="nama variasi untuk uji entry acak")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--only", nargs="*", default=None, help="hanya variasi ini (nama)")
    a = ap.parse_args()
    if a.null is not None:
        h1 = load_h1(a.symbol); d1t = d1_trend_series(h1)
        for v in variants():
            if v.name in a.null:
                print(v.name, null_test(h1, v, d1t), flush=True)
        return
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 200)
    h1 = load_h1(a.symbol)
    d1t = d1_trend_series(h1)
    bh = (h1.close.iloc[-1] / h1.close.iloc[0] - 1) * 100
    print(f"{a.symbol} H1 {h1.index[0]:%Y-%m-%d} – {h1.index[-1]:%Y-%m-%d}; buy & hold emas: {bh:+.0f}%\n")
    vs = variants()
    if a.detail:
        vs = [v for v in vs if v.name == a.detail]
    if a.only:
        vs = [v for v in vs if v.name in a.only]
    rows = []
    for v in vs:
        tr = run(h1, v, d1t)
        if tr.empty:
            continue
        la, uj = tr[tr.time < SPLIT], tr[tr.time >= SPLIT]
        yr = tr.groupby(tr.time.dt.year).r.sum()
        row = {"variasi": v.name, **stats(tr),
               "latih_avgR": round(la.r.mean(), 3), "uji_avgR": round(uj.r.mean(), 3),
               "long_totR": round(tr[tr.dir > 0].r.sum(), 1), "short_totR": round(tr[tr.dir < 0].r.sum(), 1),
               "tahun+": f"{(yr > 0).sum()}/{len(yr)}", "hold_hari": round(tr.hold_h.mean() / 24, 1), "sl_x_spread": round(tr.risk_pips.median() * PIP / MIN_SPREAD),
               "trade/bln": round(len(tr) / ((h1.index[-1] - h1.index[0]).days / 30.4), 1)}
        rows.append(row)
        if a.detail:
            print(tr.groupby([tr.time.dt.year, "dir"]).r.agg(["count", "sum", "mean"]).round(2).unstack().to_string())
    res = pd.DataFrame(rows)
    res.to_csv(f"tg_signal/data/swing_grid_{a.symbol}.csv", index=False)
    ok = res[(res.latih_avgR > 0) & (res.uji_avgR > 0)].sort_values("avgR", ascending=False)
    print(f"{len(res)} variasi; positif di latih DAN uji: {len(ok)}\n")
    print(ok.to_string(index=False))
    print("\nSisanya (urut avgR):")
    print(res.drop(ok.index).sort_values("avgR", ascending=False).head(25).to_string(index=False))


if __name__ == "__main__":
    main()
