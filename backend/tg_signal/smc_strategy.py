"""
Strategi sinyal sendiri: CHoCH + FVG + entry retest (ide dari admin, di luar topik Scalping).

    python -m tg_signal.smc_strategy                  # grid variasi, latih Agu–Sep vs uji Okt–Nov (M1)
    python -m tg_signal.smc_strategy --old            # cek ulang variasi terbaik di M5 Okt 2025 – Jul 2026

Definisi (BUY; SELL kebalikannya), dievaluasi hanya pada bar TF yang SUDAH close:
- Swing high/low: fractal ±N bar, baru "dikenal" N bar setelahnya.
- CHoCH: struktur sebelumnya bearish (swing high terakhir < swing high sebelumnya) lalu ada bar yang
  CLOSE di atas swing high terakhir (pertama kali). Varian "bos": tanpa syarat struktur bearish.
- Kaki impuls: dari low terendah setelah swing high itu sampai bar break.
- FVG: FVG bullish pertama di kaki impuls (low[j] > high[j-2]).
- Entry: limit di tepi atas FVG ("edge") atau tengah FVG ("mid"); berlaku `expire` bar TF.
- SL: low kaki impuls − buffer. TP: entry + R × risiko. Risiko harus 1.0–8.0 (10–80 pips).
- Batal sebelum fill bila harga menyentuh TP atau SL lebih dulu.
- Eksekusi di bar M1 (bid; BUY masuk di ask). Bar fill: hanya cek SL. SL & TP satu bar → SL.
- Hanya satu setup aktif (pending/terbuka) pada satu waktu.
"""
from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal.market_data import load_m1

PIP = settings.PIP_SIZE
SPLIT = pd.Timestamp("2026-10-01", tz="UTC")


@dataclass(frozen=True)
class Params:
    tf: int = 3                 # menit
    ctx: str = "choch"          # choch | bos
    entry: str = "edge"         # edge | mid
    rr: float = 2.0
    session: str = "all"        # all | ldn_ny (07:00–17:00 UTC = 14:00–24:00 WIB)
    swing_n: int = 3
    expire: int = 20            # bar TF
    min_risk: float = 1.0
    max_risk: float = 8.0

    @property
    def name(self) -> str:
        return f"M{self.tf}_{self.ctx}_{self.entry}_{self.rr:g}R_{self.session}"


@dataclass
class Setup:
    ready: np.datetime64        # waktu bar break close → order limit aktif
    expire: np.datetime64
    buy: bool
    entry: float
    sl: float
    tp: float


def resample(m1: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if minutes == 1:
        return m1
    return m1.resample(f"{minutes}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def find_setups(tf: pd.DataFrame, p: Params) -> list[Setup]:
    h, l, c = tf["high"].to_numpy(), tf["low"].to_numpy(), tf["close"].to_numpy()
    close_t = (tf.index + pd.Timedelta(minutes=p.tf)).values.astype("datetime64[ns]")
    n, N = len(tf), p.swing_n
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    used_h: set[int] = set()
    used_l: set[int] = set()
    buf = 0.2
    out: list[Setup] = []
    for i in range(2 * N + 1, n):
        k = i - N                                   # kandidat swing yang baru terkonfirmasi di bar i
        if h[k] == h[k - N:k + N + 1].max():
            highs.append((k, h[k]))
        if l[k] == l[k - N:k + N + 1].min():
            lows.append((k, l[k]))

        # ── BUY: close menembus swing high terakhir ──
        if highs and highs[-1][0] not in used_h and c[i] > highs[-1][1]:
            sh_i, sh_p = highs[-1]
            used_h.add(sh_i)
            ok = p.ctx == "bos" or (len(highs) >= 2 and sh_p < highs[-2][1])
            if ok:
                a = sh_i + 1
                leg_low_i = a + int(np.argmin(l[a:i + 1]))
                fvg = next(((h[j - 2], l[j]) for j in range(leg_low_i + 2, i + 1) if l[j] > h[j - 2]), None)
                if fvg:
                    lo, hi = fvg
                    entry = hi if p.entry == "edge" else (lo + hi) / 2
                    sl = l[leg_low_i] - buf
                    risk = entry - sl
                    if p.min_risk <= risk <= p.max_risk:
                        out.append(Setup(close_t[i], close_t[min(i + p.expire, n - 1)], True,
                                         entry, sl, entry + p.rr * risk))

        # ── SELL: close menembus swing low terakhir ──
        if lows and lows[-1][0] not in used_l and c[i] < lows[-1][1]:
            sl_i, sl_p = lows[-1]
            used_l.add(sl_i)
            ok = p.ctx == "bos" or (len(lows) >= 2 and sl_p > lows[-2][1])
            if ok:
                a = sl_i + 1
                leg_high_i = a + int(np.argmax(h[a:i + 1]))
                fvg = next(((h[j], l[j - 2]) for j in range(leg_high_i + 2, i + 1) if h[j] < l[j - 2]), None)
                if fvg:
                    lo, hi = fvg
                    entry = lo if p.entry == "edge" else (lo + hi) / 2
                    stop = h[leg_high_i] + buf
                    risk = stop - entry
                    if p.min_risk <= risk <= p.max_risk:
                        out.append(Setup(close_t[i], close_t[min(i + p.expire, n - 1)], False,
                                         entry, stop, entry - p.rr * risk))
    if p.session == "ldn_ny":
        out = [s for s in out if 7 <= pd.Timestamp(s.ready).hour < 17]
    return out


def simulate(setups: list[Setup], m1: pd.DataFrame) -> pd.DataFrame:
    t = m1.index.values.astype("datetime64[ns]")
    h, l, o = m1["high"].to_numpy(), m1["low"].to_numpy(), m1["open"].to_numpy()
    spr = m1["spread"].to_numpy()
    busy_until = np.datetime64("1970-01-01", "ns")
    rows = []
    for s in setups:
        if s.ready < busy_until:
            continue
        j = int(np.searchsorted(t, s.ready, side="left"))
        end_pending = int(np.searchsorted(t, s.expire, side="right"))
        g = 1 if s.buy else -1
        risk = abs(s.entry - s.sl)
        fill_j, outcome, exit_j = None, "EXPIRED", None
        # fase pending
        for k in range(j, min(end_pending, len(t))):
            ask_lo, bid_hi = l[k] + spr[k], h[k]
            ask_hi, bid_lo = h[k] + spr[k], l[k]
            if s.buy:
                if ask_lo <= s.entry:
                    fill_j = k
                    break
                if bid_hi >= s.tp:
                    outcome = "MISSED_TP"
                    break
                if bid_lo <= s.sl:
                    outcome = "INVALID"
                    break
            else:
                if bid_hi >= s.entry:
                    fill_j = k
                    break
                if ask_lo <= s.tp:
                    outcome = "MISSED_TP"
                    break
                if ask_hi >= s.sl:
                    outcome = "INVALID"
                    break
        if fill_j is None:
            last_k = min(k, len(t) - 1) if j < len(t) else j
            busy_until = t[last_k] if j < len(t) else busy_until
            rows.append({"ready": pd.Timestamp(s.ready, tz="UTC"), "buy": s.buy, "outcome": outcome, "r": 0.0,
                         "risk_pips": risk / PIP})
            continue
        entry = min(s.entry, o[fill_j] + spr[fill_j]) if s.buy else max(s.entry, o[fill_j])
        r = None
        for k in range(fill_j, len(t)):
            if s.buy:
                hit_sl, hit_tp = l[k] <= s.sl, h[k] >= s.tp
            else:
                hit_sl, hit_tp = h[k] + spr[k] >= s.sl, l[k] + spr[k] <= s.tp
            if hit_sl:
                r, outcome, exit_j = (s.sl - entry) * g / risk, "SL", k
                break
            if hit_tp and k > fill_j:
                r, outcome, exit_j = (s.tp - entry) * g / risk, "TP", k
                break
        if r is None:
            exit_j, outcome = len(t) - 1, "OPEN_END"
            r = ((l[-1] if s.buy else h[-1] + spr[-1]) - entry) * g / risk
        busy_until = t[exit_j]
        rows.append({"ready": pd.Timestamp(s.ready, tz="UTC"), "buy": s.buy, "outcome": outcome, "r": r,
                     "risk_pips": risk / PIP, "pips": r * risk / PIP,
                     "hold_min": (t[exit_j] - t[fill_j]) / np.timedelta64(1, "m")})
    return pd.DataFrame(rows)


def summary(tr: pd.DataFrame, days: int) -> dict:
    f = tr[tr["outcome"].isin(["TP", "SL", "OPEN_END"])] if len(tr) else tr
    if not len(f):
        return {"trades": 0}
    eq = f["r"].cumsum()
    gw, gl = f.loc[f.r > 0, "r"].sum(), -f.loc[f.r < 0, "r"].sum()
    return {
        "trades": len(f), "per_hari": round(len(f) / max(days, 1), 1),
        "WR%": round(100 * (f.r > 0).mean(), 1), "avg_R": round(f.r.mean(), 3), "total_R": round(f.r.sum(), 1),
        "PF": round(gw / gl, 2) if gl else float("inf"), "maxDD_R": round(float((eq.cummax() - eq).max()), 1),
        "SL_pips": round(f.risk_pips.median(), 1), "USD@0.01": round(f.pips.sum() * settings.USD_PER_PIP_001, 1),
    }


def grid() -> list[Params]:
    return [Params(tf=tf, ctx=ctx, entry=e, rr=rr, session=s) for tf, ctx, e, rr, s in
            itertools.product((3, 5), ("choch", "bos"), ("edge", "mid"), (1.5, 2.0, 3.0), ("all", "ldn_ny"))]


def run_period(m1: pd.DataFrame, ps: list[Params], start, end, exec_bars: pd.DataFrame | None = None) -> pd.DataFrame:
    sub = m1[(m1.index >= start - pd.Timedelta(days=2)) & (m1.index < end)]
    ex = sub if exec_bars is None else exec_bars[(exec_bars.index >= start - pd.Timedelta(days=2))
                                                 & (exec_bars.index < end)]
    days = int(np.busday_count(start.date(), end.date()))
    rows = []
    tf_cache: dict[int, pd.DataFrame] = {}
    for p in ps:
        tf = tf_cache.setdefault(p.tf, resample(sub, p.tf))
        st = [s for s in find_setups(tf, p) if start <= pd.Timestamp(s.ready, tz="UTC") < end]
        rows.append({"variasi": p.name, **summary(simulate(st, ex), days)})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest strategi CHoCH + FVG")
    ap.add_argument("--old", action="store_true", help="validasi di M5 Okt 2025 – Jul 2026")
    args = ap.parse_args()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)

    if args.old:
        m5 = load_m1("M5")
        ps = [p for p in grid() if p.tf == 5]
        res = run_period(m5, ps, pd.Timestamp("2025-10-01", tz="UTC"), pd.Timestamp("2026-08-01", tz="UTC"))
        print("Periode lama Okt 2025 – Jul 2026, deteksi & eksekusi di bar M5 (pesimis):")
        print(res.sort_values("avg_R", ascending=False).to_string(index=False))
        return

    m1 = load_m1("M1")
    a = pd.Timestamp("2026-08-01", tz="UTC")
    b = pd.Timestamp(m1.index[-1]).ceil("D")
    ps = grid()
    tr = run_period(m1, ps, a, SPLIT)
    te = run_period(m1, ps, SPLIT, b)
    res = tr.merge(te, on="variasi", suffixes=("_latih", "_uji"))
    cols = ["variasi", "trades_latih", "WR%_latih", "avg_R_latih", "total_R_latih",
            "trades_uji", "per_hari_uji", "WR%_uji", "avg_R_uji", "total_R_uji", "PF_uji", "maxDD_R_uji",
            "SL_pips_uji", "USD@0.01_uji"]
    res = res.sort_values("avg_R_latih", ascending=False)[cols]
    print("Latih Agu–Sep 2026 | Uji 1 Okt – 11 Nov 2026 (M1). Diurutkan menurut avg_R di data LATIH.")
    print(res.to_string(index=False))
    res.to_csv(settings.DATA_DIR / "smc_grid.csv", index=False)
    both = res[(res["avg_R_latih"] > 0) & (res["avg_R_uji"] > 0)]
    print(f"\nVariasi positif di latih DAN uji: {len(both)} dari {len(res)}")


if __name__ == "__main__":
    main()
