"""
Opening Range Breakout (ORB) XAUUSD di bar M1 — hanya backtest.

    python -m tg_signal.orb            # grid, latih < Apr 2026 / uji ≥ Apr 2026

Pembukaan (jam lokal, dikonversi ke UTC per hari → DST otomatis):
  london 08:00 Europe/London | comex 08:20 America/New_York | ny 09:30 America/New_York
Opening range (OR) = high/low bar M1 [open, open + L menit).
Breakout: close pertama di luar OR dalam 120 menit setelah OR selesai.
  conf m1 = close bar M1 | m5 = close bar M5 (bar M1 penutup bucket 5 menit).
  Hanya breakout pertama per sesi per hari (gagal = selesai).
Entry: market = open bar berikutnya | retest = limit di tepi OR (berlaku 30 bar; batal bila TP dulu).
SL: opp = sisi seberang OR | mid = tengah OR (− $0.1).  Risiko ≥ $1.
TP: RR × risiko (1.5 / 2 / 3) | eod = tanpa TP. Semua posisi ditutup paksa open + 6 jam.
Filter: bias with = EMA50 H1 searah & miring > 0.1 ATR (sama pro_live);
        width atr = lebar OR 0.3–2.5 × ATR14 H1 (buang OR terlalu sempit / terlalu lebar).
Harga bar = BID; BUY masuk di ask, SELL keluar di ask. SL & TP satu bar → SL. Bar fill limit: hanya SL.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal.market_data import load_m1
from tg_signal.session_sweep import Data, simulate

SPLIT = pd.Timestamp("2026-04-01", tz="UTC")
OPENS = {"london": ("Europe/London", 8, 0), "comex": ("America/New_York", 8, 20),
         "ny": ("America/New_York", 9, 30)}
BREAK_WAIT = 120
RETEST_WAIT = 30
HOLD_MIN = 6 * 60
WIDTH_ATR = (0.3, 2.5)
RISK_MIN = 1.0


@dataclass(frozen=True)
class Cfg:
    session: str
    or_min: int
    conf: str = "m1"
    entry: str = "market"
    sl: str = "opp"
    tp: str = "2"
    bias: str = "none"
    width: str = "none"

    @property
    def name(self) -> str:
        return (f"{self.session}_OR{self.or_min}_{self.conf}_{self.entry}_SL{self.sl}_TP{self.tp}"
                f"_{self.bias}_{self.width}")


def open_index(d: Data, session: str) -> list[int]:
    """Indeks bar M1 pembukaan sesi untuk tiap hari kerja (bar pertama ≥ jam buka)."""
    tz, hh, mm = OPENS[session]
    out = []
    for day, a, b in d.days:
        if day.weekday() >= 5:
            continue
        loc = pd.Timestamp(year=day.year, month=day.month, day=day.day, hour=hh, minute=mm, tz=tz)
        ts = np.datetime64(loc.tz_convert("UTC").tz_localize(None), "ns")
        i = int(np.searchsorted(d.t, ts, side="left"))
        if a <= i < b and d.t[i] - ts < np.timedelta64(5, "m"):
            out.append(i)
    return out


def run(d: Data, cfg: Cfg, opens: list[int]) -> pd.DataFrame:
    out = []
    one_min = np.timedelta64(1, "m")
    for i0 in opens:
        t0 = d.t[i0]
        i_or = int(np.searchsorted(d.t, t0 + cfg.or_min * one_min, side="left"))
        i_end = int(np.searchsorted(d.t, t0 + (cfg.or_min + BREAK_WAIT) * one_min, side="left"))
        i_exit = int(np.searchsorted(d.t, t0 + HOLD_MIN * one_min, side="left"))
        if i_or - i0 < cfg.or_min * 0.8 or i_exit >= d.n:
            continue
        H0, L0 = d.arr[True][1], d.arr[True][2]
        hi, lo = H0[i0:i_or].max(), L0[i0:i_or].min()
        width = hi - lo
        atr = d.atr[i_or - 1]
        if cfg.width == "atr" and not (np.isfinite(atr) and WIDTH_ATR[0] * atr <= width <= WIDTH_ATR[1] * atr):
            continue
        c = d.arr[True][3]
        mins = d.mins
        sig = None
        for i in range(i_or, min(i_end, i_exit - 1)):
            if cfg.conf == "m5" and (mins[i] + 1) % 5 != 0:
                continue
            if c[i] > hi:
                sig = (i, True)
                break
            if c[i] < lo:
                sig = (i, False)
                break
        if sig is None:
            continue
        i, is_buy = sig
        if cfg.bias == "with" and not d.bias[is_buy][i]:
            continue
        sgn = 1 if is_buy else -1
        edge, opp = (hi, lo) if is_buy else (-lo, -hi)          # ruang BUY
        sl = opp if cfg.sl == "opp" else (edge + opp) / 2
        sl -= 0.1
        O = d.arr[is_buy][0]
        if cfg.entry == "market":
            entry = O[i + 1] + (d.spr[i + 1] if is_buy else 0.0)
            ref, lim = entry, None
        else:
            entry, ref, lim = None, edge, edge
        risk = ref - sl
        if risk < RISK_MIN:
            continue
        tp = np.inf if cfg.tp == "eod" else ref + float(cfg.tp) * risk
        r = simulate(d, is_buy, i + 1, i_exit, entry, lim, sl, tp, RETEST_WAIT)
        if r is None:
            continue
        e, x, ent, R, why = r
        out.append({"time": pd.Timestamp(d.t[e], tz="UTC"), "dir": "BUY" if is_buy else "SELL",
                    "entry": round(sgn * ent, 2), "or_width": round(width, 2),
                    "risk_pips": round((ent - sl) / settings.PIP_SIZE, 1), "R": round(R, 3), "outcome": why})
    return pd.DataFrame(out)


def stats(g: pd.DataFrame) -> dict:
    if g.empty:
        return {"n": 0, "wr%": 0.0, "R": 0.0, "avgR": 0.0, "PF": 0.0, "DD": 0.0}
    r = g.sort_values("time")["R"]
    eq = r.cumsum()
    gl = -r[r < 0].sum()
    return {"n": len(r), "wr%": round(100 * (r > 0).mean(), 1), "R": round(r.sum(), 1), "avgR": round(r.mean(), 3),
            "PF": round(r[r > 0].sum() / gl, 2) if gl else np.inf, "DD": round(float((eq.cummax() - eq).max()), 1)}


def grid() -> list[Cfg]:
    return [Cfg(*x) for x in itertools.product(
        OPENS, (5, 15, 30, 60), ("m1", "m5"), ("market", "retest"), ("opp", "mid"), ("1.5", "2", "3", "eod"),
        ("none", "with"), ("none", "atr"))]


def main() -> None:
    df = load_m1("M1")
    df = df[df.index >= "2025-06-16"]
    d = Data(df)
    opens = {s: open_index(d, s) for s in OPENS}
    print(f"Data M1 {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d} | hari sesi: "
          + ", ".join(f"{s} {len(v)}" for s, v in opens.items()), flush=True)
    rows, allt = [], []
    for cfg in grid():
        t = run(d, cfg, opens[cfg.session])
        if t.empty:
            continue
        t["cfg"] = cfg.name
        allt.append(t)
        tr, te = stats(t[t.time < SPLIT]), stats(t[t.time >= SPLIT])
        rows.append({"cfg": cfg.name, **cfg.__dict__, "risk_med": t.risk_pips.median(),
                     **{f"tr_{k}": v for k, v in tr.items()}, **{f"te_{k}": v for k, v in te.items()}})
    res = pd.DataFrame(rows)
    res.to_csv(settings.DATA_DIR / "orb_grid.csv", index=False)
    pd.concat(allt).to_csv(settings.DATA_DIR / "orb_trades.csv", index=False)
    print(f"{len(res)} variasi | median PF latih {res.tr_PF.median():.2f} uji {res.te_PF.median():.2f}")
    with pd.option_context("display.width", 250, "display.max_rows", 200):
        for col in ("session", "or_min", "conf", "entry", "sl", "tp", "bias", "width"):
            print(f"\n── median per {col} ──\n" + res.groupby(col)[["tr_PF", "te_PF", "tr_avgR", "te_avgR"]]
                  .median().round(3).to_string())
        ok = res[(res.tr_PF > 1.15) & (res.te_PF > 1.15) & (res.tr_n >= 60) & (res.te_n >= 50)]
        print(f"\nPF > 1.15 latih & uji (n ≥ 60/50): {len(ok)} dari {len(res)}")
        cols = ["cfg", "risk_med", "tr_n", "tr_wr%", "tr_avgR", "tr_PF", "tr_DD", "te_n", "te_wr%", "te_avgR",
                "te_PF", "te_DD"]
        print(ok.sort_values("te_R", ascending=False)[cols].head(40).to_string(index=False))


if __name__ == "__main__":
    main()


# ── Logika sinyal untuk runner live (orb_live) — fungsi murni, diverifikasi sama dengan run() ──────────
LIVE_CFG = Cfg("ny", 15, "m5", "market", "opp", "2", "with", "none")


def session_open_utc(day, session: str = "ny") -> pd.Timestamp:
    """Jam buka sesi (UTC) untuk tanggal `day` (tanggal kalender di zona sesi)."""
    tz, hh, mm = OPENS[session]
    day = pd.Timestamp(day)
    return pd.Timestamp(year=day.year, month=day.month, day=day.day, hour=hh, minute=mm, tz=tz).tz_convert("UTC")


def h1_bias(h1: pd.DataFrame) -> pd.DataFrame:
    """Bias EMA50 H1 + slope > 0.1 ATR14 per bar H1 (index = waktu buka bar, UTC). Sama dengan session_sweep.Data."""
    ema = h1.close.ewm(span=50, adjust=False).mean()
    atr = (h1.high - h1.low).rolling(14).mean()
    slope = ema.diff(3)
    return pd.DataFrame({"up": (h1.close > ema) & (slope > 0.1 * atr),
                         "dn": (h1.close < ema) & (slope < -0.1 * atr)}, index=h1.index)


def bias_at(bias: pd.DataFrame, t: pd.Timestamp, is_buy: bool) -> bool:
    """Bias dari bar H1 terakhir yang sudah close pada waktu t."""
    closed = bias[bias.index + pd.Timedelta(minutes=60) <= t]
    if closed.empty:
        return False
    return bool(closed.iloc[-1]["up" if is_buy else "dn"])


def find_breakout(m1: pd.DataFrame, m5: pd.DataFrame, open_utc: pd.Timestamp, cfg: Cfg = LIVE_CFG) -> dict | None:
    """Breakout pertama setelah opening range. m1/m5 = bar yang SUDAH close (index = waktu buka, UTC).
    Return dict(or_hi, or_lo, dir, bar, close_time) atau dict tanpa 'dir' bila OR ada tapi belum breakout,
    atau None bila OR belum lengkap."""
    or_end = open_utc + pd.Timedelta(minutes=cfg.or_min)
    rng = m1[(m1.index >= open_utc) & (m1.index < or_end)]
    if rng.empty or m1.index[-1] < or_end - pd.Timedelta(minutes=1) or len(rng) < cfg.or_min * 0.8:
        return None
    hi, lo = float(rng.high.max()), float(rng.low.min())
    out = {"or_hi": hi, "or_lo": lo}
    w = m5[(m5.index >= or_end) & (m5.index < or_end + pd.Timedelta(minutes=BREAK_WAIT))]
    for t, c in w.close.items():
        if c > hi or c < lo:
            out.update(dir="BUY" if c > hi else "SELL", bar=t, close_time=t + pd.Timedelta(minutes=5))
            break
    return out


def plan_order(sig: dict, price: float) -> tuple[float, float, float] | None:
    """(sl, tp, risk) untuk entry market di `price` (ask BUY / bid SELL). None bila risiko < RISK_MIN."""
    if sig["dir"] == "BUY":
        sl = sig["or_lo"] - 0.1
        risk = price - sl
        tp = price + float(LIVE_CFG.tp) * risk
    else:
        sl = sig["or_hi"] + 0.1
        risk = sl - price
        tp = price - float(LIVE_CFG.tp) * risk
    return None if risk < RISK_MIN else (sl, tp, risk)
