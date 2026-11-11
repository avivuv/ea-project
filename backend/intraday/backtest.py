"""
Backtest strategi intraday XAUUSD di bar M5 (Okt 2025 – Nov 2026). Hasil dalam R (kelipatan risiko).

    python -m intraday.backtest                 # dua strategi, semua variasi, latih vs uji
    python -m intraday.backtest --detail NAMA   # rincian bulanan satu variasi

Waktu = UTC (server Exness). Asia 00–07 UTC (07–14 WIB), London 07 UTC (14 WIB), NY 13:30 UTC (20:30 WIB).

S1 — Sweep likuiditas + CHoCH M5:
    Level: high/low Asia dan/atau high/low hari sebelumnya. Di jam 07–16 UTC harga menembus level (sweep),
    lalu dalam ≤ 2 jam ada bar yang CLOSE menembus struktur kecil arah berlawanan (low terendah 6 bar
    sebelum puncak sweep untuk SELL) = CHoCH. Entry limit di FVG pertama pada kaki balik (tepi/tengah).
    SL di luar ekstrem sweep + buffer. TP 2R / 3R / sisi seberang range Asia. Tutup paksa 20:00 UTC.
S2 — Opening Range Breakout:
    Range 15/30 menit pertama sesi London atau NY. Bar M5 pertama yang close di luar range → entry market
    di open bar berikutnya. SL di sisi seberang range (atau tengah range). TP 1,5R / 2R / tahan sampai
    akhir sesi. Satu trade per sesi.

Eksekusi konservatif: harga bar = BID, BUY bayar spread saat masuk, SELL saat keluar; SL & TP di bar
yang sama → SL; bar fill limit hanya cek SL. Satu posisi per strategi pada satu waktu.
"""
from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tg_signal.market_data import load_m1

SPLIT = pd.Timestamp("2026-05-01", tz="UTC")
BUF = 0.3


@dataclass
class Order:
    buy: bool
    kind: str                   # limit | market
    entry: float                # untuk market: diabaikan (pakai open bar)
    sl: float
    tp: float | None            # None = tahan sampai tutup paksa
    active: pd.Timestamp
    cancel: pd.Timestamp
    force: pd.Timestamp


class Bars:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.t = df.index.values.astype("datetime64[ns]")
        self.o, self.h, self.l, self.c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
        self.s = df["spread"].to_numpy()

    def idx(self, ts: pd.Timestamp) -> int:
        return int(np.searchsorted(self.t, np.datetime64(ts.tz_convert(None)), side="left"))


def simulate(orders: list[Order], b: Bars) -> pd.DataFrame:
    rows, busy = [], np.datetime64("1970-01-01")
    for od in orders:
        j = b.idx(od.active)
        if j >= len(b.t) or b.t[j] < busy:
            continue
        jc, jf = b.idx(od.cancel), b.idx(od.force)
        g = 1 if od.buy else -1
        fill, why = None, "EXPIRED"
        if od.kind == "market":
            fill = j
            entry = b.o[j] + (b.s[j] if od.buy else 0.0)
        else:
            entry = od.entry
            for k in range(j, min(jc, len(b.t))):
                lo_ask, hi_bid = b.l[k] + b.s[k], b.h[k]
                if od.buy:
                    if lo_ask <= entry:
                        fill = k
                        entry = min(entry, b.o[k] + b.s[k])
                        break
                    if od.tp is not None and hi_bid >= od.tp:
                        why = "MISSED_TP"; break
                    if b.l[k] <= od.sl:
                        why = "INVALID"; break
                else:
                    if hi_bid >= entry:
                        fill = k
                        entry = max(entry, b.o[k])
                        break
                    if od.tp is not None and lo_ask <= od.tp:
                        why = "MISSED_TP"; break
                    if b.h[k] + b.s[k] >= od.sl:
                        why = "INVALID"; break
        if fill is None:
            rows.append({"time": od.active, "buy": od.buy, "outcome": why, "r": np.nan})
            continue
        risk = abs(entry - od.sl)
        if risk <= 0:
            continue
        r, out, k = None, "", fill
        for k in range(fill, min(jf, len(b.t))):
            if od.buy:
                hit_sl, hit_tp = b.l[k] <= od.sl, od.tp is not None and b.h[k] >= od.tp
            else:
                hit_sl, hit_tp = b.h[k] + b.s[k] >= od.sl, od.tp is not None and b.l[k] + b.s[k] <= od.tp
            if hit_sl:
                r, out = (od.sl - entry) * g / risk, "SL"; break
            if hit_tp and not (od.kind == "limit" and k == fill):
                r, out = (od.tp - entry) * g / risk, "TP"; break
        if r is None:
            k = min(jf, len(b.t)) - 1
            px = b.c[k] if od.buy else b.c[k] + b.s[k]
            r, out = (px - entry) * g / risk, "TIME"
        busy = b.t[k]
        rows.append({"time": od.active, "buy": od.buy, "outcome": out, "r": r, "risk": risk})
    return pd.DataFrame(rows)


# ── S1: sweep + CHoCH ───────────────────────────────────────────────────────
@dataclass(frozen=True)
class S1:
    levels: str = "both"        # asia | pd | both
    entry: str = "edge"         # edge | mid
    tp: str = "2R"              # 2R | 3R | opp
    struct_bars: int = 6
    max_wait: int = 24          # bar M5 setelah ekstrem sweep untuk CHoCH

    @property
    def name(self) -> str:
        return f"S1_sweep_{self.levels}_{self.entry}_{self.tp}"


def s1_orders(df: pd.DataFrame, p: S1) -> list[Order]:
    out: list[Order] = []
    days = df.groupby(df.index.normalize())
    prev = None
    for day, d in days:
        if len(d) < 150:                                     # hari libur / data tipis
            prev = d if len(d) else prev
            continue
        asia = d[d.index.hour < 7]
        sess = d[(d.index.hour >= 7) & (d.index.hour < 16)]
        if len(asia) < 50 or len(sess) < 50:
            prev = d
            continue
        ah, al = asia["high"].max(), asia["low"].min()
        lv_hi, lv_lo = [], []
        if p.levels in ("asia", "both"):
            lv_hi.append(ah); lv_lo.append(al)
        if p.levels in ("pd", "both") and prev is not None:
            lv_hi.append(prev["high"].max()); lv_lo.append(prev["low"].min())
        prev = d
        h, l, c = sess["high"].to_numpy(), sess["low"].to_numpy(), sess["close"].to_numpy()
        t = sess.index
        full_h, full_l = d["high"].to_numpy(), d["low"].to_numpy()
        off = d.index.get_loc(t[0])
        force = day + pd.Timedelta(hours=20)
        sess_end = day + pd.Timedelta(hours=16)
        for side in ("high", "low"):
            levels = lv_hi if side == "high" else lv_lo
            if not levels:
                continue
            ext = None
            for i in range(len(sess)):
                swept = (h[i] > min(levels)) if side == "high" else (l[i] < max(levels))
                if ext is None:
                    if swept:
                        ext = i
                    continue
                if side == "high" and h[i] > h[ext]:
                    ext = i
                    continue
                if side == "low" and l[i] < l[ext]:
                    ext = i
                    continue
                if i - ext > p.max_wait:
                    break
                gi = off + ext
                if side == "high":
                    struct = full_l[max(0, gi - p.struct_bars):gi].min()
                    if c[i] >= struct:
                        continue
                    fvg = next(((h[j], l[j - 2]) for j in range(ext + 2, i + 1) if h[j] < l[j - 2]), None)
                    if not fvg:
                        break
                    lo, hi = fvg
                    entry = lo if p.entry == "edge" else (lo + hi) / 2
                    sl = h[ext] + BUF
                    risk = sl - entry
                    tp = entry - (2 if p.tp == "2R" else 3) * risk if p.tp != "opp" else al
                    buy = False
                else:
                    struct = full_h[max(0, gi - p.struct_bars):gi].max()
                    if c[i] <= struct:
                        continue
                    fvg = next(((h[j - 2], l[j]) for j in range(ext + 2, i + 1) if l[j] > h[j - 2]), None)
                    if not fvg:
                        break
                    lo, hi = fvg
                    entry = hi if p.entry == "edge" else (lo + hi) / 2
                    sl = l[ext] - BUF
                    risk = entry - sl
                    tp = entry + (2 if p.tp == "2R" else 3) * risk if p.tp != "opp" else ah
                    buy = True
                if not (1.0 <= risk <= 15.0):
                    break
                if p.tp == "opp" and abs(tp - entry) < 1.5 * risk:
                    break
                act = t[i] + pd.Timedelta(minutes=5)
                out.append(Order(buy, "limit", entry, sl, tp, act,
                                 min(act + pd.Timedelta(minutes=60), sess_end), force))
                break
    out.sort(key=lambda o: o.active)
    return out


# ── S2: opening range breakout ──────────────────────────────────────────────
SESSIONS = {"london": (7, 0, 10, 16), "ny": (13, 30, 16, 20)}   # buka (jam, menit), batas trigger, tutup paksa


@dataclass(frozen=True)
class S2:
    session: str = "london"
    rng_min: int = 30
    sl: str = "opp"             # opp | mid
    tp: str = "2R"              # 1.5R | 2R | eod

    @property
    def name(self) -> str:
        return f"S2_orb_{self.session}_{self.rng_min}m_{self.sl}_{self.tp}"


def s2_orders(df: pd.DataFrame, p: S2, tf_min: int = 5) -> list[Order]:
    oh, om, trig_h, force_h = SESSIONS[p.session]
    out = []
    for day, d in df.groupby(df.index.normalize()):
        o0 = day + pd.Timedelta(hours=oh, minutes=om)
        rng = d[(d.index >= o0) & (d.index < o0 + pd.Timedelta(minutes=p.rng_min))]
        if len(rng) < max(1, p.rng_min // tf_min):
            continue
        hi, lo = rng["high"].max(), rng["low"].min()
        if not (1.5 <= hi - lo <= 15.0):
            continue
        after = d[(d.index >= o0 + pd.Timedelta(minutes=p.rng_min)) & (d.index < day + pd.Timedelta(hours=trig_h))]
        for ts, row in after.iterrows():
            buy = row["close"] > hi
            sell = row["close"] < lo
            if not (buy or sell):
                continue
            sl = (lo if buy else hi) if p.sl == "opp" else (hi + lo) / 2
            ref = row["close"]
            risk = abs(ref - sl)
            if risk <= 0.5:
                break
            mult = {"1.5R": 1.5, "2R": 2.0}.get(p.tp)
            tp = None if mult is None else (ref + mult * risk if buy else ref - mult * risk)
            act = ts + pd.Timedelta(minutes=tf_min)
            out.append(Order(buy, "market", ref, sl - (BUF if buy else -BUF), tp, act, act,
                             day + pd.Timedelta(hours=force_h)))
            break
    return out


# ── Ringkasan ───────────────────────────────────────────────────────────────
def stats(tr: pd.DataFrame, months: float) -> dict:
    f = tr.dropna(subset=["r"]) if len(tr) else tr
    if not len(f):
        return {"trades": 0}
    eq = f["r"].cumsum()
    gw, gl = f.loc[f.r > 0, "r"].sum(), -f.loc[f.r < 0, "r"].sum()
    return {"trades": len(f), "per_bln": round(len(f) / months, 1), "WR%": round(100 * (f.r > 0).mean(), 1),
            "avgR": round(f.r.mean(), 3), "totR": round(f.r.sum(), 1),
            "PF": round(gw / gl, 2) if gl else np.inf, "DD_R": round(float((eq.cummax() - eq).max()), 1)}


def variants():
    v1 = [S1(lv, e, tp) for lv, e, tp in itertools.product(("asia", "pd", "both"), ("edge", "mid"), ("2R", "3R", "opp"))]
    v2 = [S2(s, m, sl, tp) for s, m, sl, tp in itertools.product(("london", "ny"), (15, 30), ("opp", "mid"),
                                                                  ("1.5R", "2R", "eod"))]
    return v1 + v2


def run(p, df: pd.DataFrame, b: Bars) -> pd.DataFrame:
    orders = s1_orders(df, p) if isinstance(p, S1) else s2_orders(df, p)
    return simulate(orders, b)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", default=None)
    args = ap.parse_args()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    df = load_m1("M5")
    b = Bars(df)
    m_tr = (SPLIT - df.index[0]).days / 30.4
    m_te = (df.index[-1] - SPLIT).days / 30.4

    if args.detail:
        p = next(v for v in variants() if v.name == args.detail)
        tr = run(p, df, b).dropna(subset=["r"])
        tr["bulan"] = tr["time"].dt.strftime("%Y-%m")
        print(tr.groupby("bulan")["r"].agg(trades="size", totR="sum", avgR="mean",
                                           WR=lambda x: 100 * (x > 0).mean()).round(2).to_string())
        print(stats(tr, (df.index[-1] - df.index[0]).days / 30.4))
        return

    rows = []
    for p in variants():
        tr = run(p, df, b)
        a = stats(tr[tr["time"] < SPLIT], m_tr) if len(tr) else {}
        z = stats(tr[tr["time"] >= SPLIT], m_te) if len(tr) else {}
        rows.append({"variasi": p.name, **{f"{k}_latih": v for k, v in a.items()},
                     **{f"{k}_uji": v for k, v in z.items()}})
    res = pd.DataFrame(rows).sort_values("avgR_latih", ascending=False)
    cols = ["variasi", "trades_latih", "WR%_latih", "avgR_latih", "totR_latih", "DD_R_latih",
            "trades_uji", "per_bln_uji", "WR%_uji", "avgR_uji", "totR_uji", "PF_uji", "DD_R_uji"]
    print(f"Latih: {df.index[0]:%Y-%m-%d} – {SPLIT:%Y-%m-%d} | Uji: {SPLIT:%Y-%m-%d} – {df.index[-1]:%Y-%m-%d} "
          f"(bar M5). Urut menurut avgR LATIH.")
    print(res[cols].to_string(index=False))
    ok = res[(res["avgR_latih"] > 0) & (res["avgR_uji"] > 0)]
    print(f"\nPositif di latih DAN uji: {len(ok)} dari {len(res)}")
    res.to_csv("tg_signal/data/intraday_grid.csv", index=False)


if __name__ == "__main__":
    main()
