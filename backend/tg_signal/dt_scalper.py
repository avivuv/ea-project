"""
Scalper sendiri meniru indikator admin (POI + Apache channel + RSI + E/T by DNDFX), XAUUSD M1.
Tujuan: menghasilkan sinyal sendiri tanpa menunggu Telegram. Hanya backtest.

    python -m tg_signal.dt_scalper                # grid variasi, latih < Apr 2026 / uji ≥ Apr 2026
    python -m tg_signal.dt_scalper --match        # seberapa banyak sinyal admin tertangkap zona kita

Semua logika di "ruang BUY" (zona demand); SELL dihitung dengan harga dinegasikan.

Zona (cfg.zone):
  swing : pivot low M1 (fractal ±PIV) → zona [low, min(open, close)] candle pivot (wick s/d badan),
          tinggi dipaksa ZMIN..ZMAX. Aktif setelah harga menjauh ≥ cfg.away dari tepi atas.
  poi   : FVG / OB / IFVG M1 dari detectors/poi.py (ukuran ≥ $0.5), juga butuh menjauh ≥ cfg.away.
  Zona mati saat disentuh (dipakai sekali), close di bawah tepi bawah, atau umur > MAX_AGE.
Entry (meniru "BUY NOW" admin di ZERO): bar menyentuh tepi atas zona → limit terisi di tepi atas
  (atau open bila gap). SL/TP = cfg.sl / cfg.tp pips dari entry.
Konfirmasi (cfg.conf):
  none : langsung saat sentuh
  rsi  : RSI(14) M1 bar sebelumnya ≤ cfg.rsi_lv (oversold; SELL ≥ 100 − rsi_lv)
  chan : close bar sebelumnya di separuh bawah channel regresi linier CH_LEN bar (Apache)
  et   : setelah sentuh, tunggu ≤ ET_WAIT bar candle E (engulfing bullish) atau T (2 candle bullish,
         close ke-2 > high ke-1) selama zona belum jebol → market di open bar berikutnya
  Kombinasi ditulis dengan '+', mis. "rsi+chan".
Sesi (cfg.session): pagi = 00:00–07:30 UTC (07:00–14:30 WIB, jam analis POI) | all.
Satu posisi per arah. Harga bar = BID; BUY masuk di ask, SELL keluar di ask. SL & TP satu bar → SL.
"""
from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal.detectors.poi import find_pois
from tg_signal.market_data import load_m1

PIP = settings.PIP_SIZE
SPLIT = pd.Timestamp("2026-04-01", tz="UTC")
PIV = 3
ZMIN, ZMAX = 0.5, 8.0
MAX_AGE = 6 * 60             # bar M1
CH_LEN = 60
ET_WAIT = 10
RSI_LEN = 14


@dataclass(frozen=True)
class Cfg:
    zone: str = "swing"
    away: float = 3.0         # $ — harga harus menjauh dulu dari zona sebelum sentuhan dihitung
    conf: str = "none"
    rsi_lv: float = 30.0
    tp: float = 30.0          # pips
    sl: float = 30.0
    session: str = "pagi"

    @property
    def name(self) -> str:
        c = self.conf.replace("rsi", f"rsi{self.rsi_lv:g}")
        return f"{self.zone}_away{self.away:g}_{c}_TP{self.tp:g}_SL{self.sl:g}_{self.session}"


def rsi(c: np.ndarray, n: int = RSI_LEN) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.clip(d, 0, None)).ewm(alpha=1 / n, adjust=False).mean()
    dn = pd.Series(np.clip(-d, 0, None)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).to_numpy()


def channel_pos(c: np.ndarray, n: int = CH_LEN) -> np.ndarray:
    """Posisi close terhadap garis regresi linier n bar terakhir: (close − fit) / (2·std residual).
    < 0 = di bawah midline. Dihitung pada bar i memakai bar i−n+1..i."""
    x = np.arange(n, dtype=float)
    sx, sxx = x.sum(), (x * x).sum()
    cs = np.convolve(c, np.ones(n), "valid")
    cxs = np.convolve(c, x[::-1], "valid")          # Σ x·c dengan x = 0..n−1 dari bar terlama
    den = n * sxx - sx * sx
    b = (n * cxs - sx * cs) / den
    a = (cs - b * sx) / n
    fit_last = a + b * (n - 1)
    c2 = np.convolve(c * c, np.ones(n), "valid")
    # residual variance ≈ var(c) − b²·var(x)
    var = np.clip(c2 / n - (cs / n) ** 2 - b * b * (sxx / n - (sx / n) ** 2), 1e-9, None)
    out = np.full(len(c), np.nan)
    out[n - 1:] = (c[n - 1:] - fit_last) / (2 * np.sqrt(var))
    return out


def swing_zones(o, h, l, c) -> list[tuple]:
    """(aktif_mulai, top, bottom, kind) zona demand dari pivot low. aktif_mulai = bar konfirmasi + 1."""
    n = len(c)
    win = np.lib.stride_tricks.sliding_window_view(l, 2 * PIV + 1).min(axis=1)
    piv = np.zeros(n, bool)
    piv[PIV:n - PIV] = l[PIV:n - PIV] <= win
    out = []
    for j in np.flatnonzero(piv):
        bot = l[j]
        top = min(o[j], c[j])
        top = min(max(top, bot + ZMIN), bot + ZMAX)
        out.append((j + PIV + 1, top, bot, "SWING"))
    return out


class Market:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.t = df.index.values.astype("datetime64[ns]")
        self.n = len(df)
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.spr = df["spread"].to_numpy(float)
        mins = df.index.hour * 60 + df.index.minute
        self.pagi = np.asarray(mins < 7 * 60 + 30)
        self.arr = {True: (o, h, l, c), False: (-o, -l, -h, -c)}
        r = rsi(c)
        self.rsi = {True: r, False: 100 - r}
        cp = channel_pos(c)
        self.chan = {True: cp, False: -cp}
        self.zones = {}
        for b, (o_, h_, l_, c_) in self.arr.items():
            sw = swing_zones(o_, h_, l_, c_)
            po = [(p.created + 1, p.top, p.bottom, p.kind) for p in find_pois(o_, h_, l_, c_, min_size=0.5)]
            self.zones[(b, "swing")] = sorted(sw)
            self.zones[(b, "poi")] = sorted(po)
            self.zones[(b, "both")] = sorted(sw + po)


def run_side(mk: Market, cfg: Cfg, is_buy: bool) -> list[dict]:
    O, H, L, C = mk.arr[is_buy]
    spr, n = mk.spr, mk.n
    zones = mk.zones[(is_buy, cfg.zone)]
    rs, ch = mk.rsi[is_buy], mk.chan[is_buy]
    conf = set(cfg.conf.split("+"))
    sgn = 1 if is_buy else -1
    tp_d, sl_d = cfg.tp * PIP, cfg.sl * PIP
    trades = []
    live: list[list] = []        # [start, top, bottom, kind, armed]
    ptr = 0
    pos = None                   # dict posisi terbuka
    wait = None                  # zona yang sudah disentuh, menunggu E/T

    def open_at(i, entry, kind):
        nonlocal pos
        pos = {"i": i, "entry": entry, "sl": entry - sl_d, "tp": entry + tp_d, "kind": kind}

    for i in range(CH_LEN + 5, n - 1):
        cost = spr[i] if is_buy else 0.0
        xadj = 0.0 if is_buy else spr[i]
        # kelola posisi
        if pos is not None:
            if i > pos["i"] or pos.get("market"):
                if L[i] - xadj <= pos["sl"]:
                    trades.append((pos, i, -cfg.sl, "SL"))
                    pos = None
                elif H[i] - xadj >= pos["tp"]:
                    trades.append((pos, i, cfg.tp, "TP"))
                    pos = None
            elif L[i] - xadj <= pos["sl"]:                # bar fill limit: hanya SL
                trades.append((pos, i, -cfg.sl, "SL"))
                pos = None
        # zona baru
        while ptr < len(zones) and zones[ptr][0] <= i:
            z = zones[ptr]
            live.append([z[0], z[1], z[2], z[3], False])
            ptr += 1
        keep = []
        for z in live:
            if i - z[0] > MAX_AGE or C[i - 1] < z[2]:
                continue
            if not z[4] and H[i - 1] >= z[1] + cfg.away:
                z[4] = True
            keep.append(z)
        live = keep

        # menunggu konfirmasi E/T
        if wait is not None:
            z, t0 = wait
            if C[i] < z[2] or i - t0 > ET_WAIT:
                wait = None
            elif pos is None:
                eng = C[i - 1] < O[i - 1] and C[i] > O[i] and C[i] >= O[i - 1]
                trig = C[i - 1] > O[i - 1] and C[i] > O[i] and C[i] > H[i - 1]
                if eng or trig:
                    entry = O[i + 1] + (spr[i + 1] if is_buy else 0.0)
                    open_at(i + 1, entry, z[3])
                    pos["market"] = True
                    pos["i"] = i + 1
                    wait = None
            continue

        if pos is not None:
            continue
        if cfg.session == "pagi" and not mk.pagi[i]:
            continue
        # sentuhan: zona aktif tertinggi yang tersentuh bar ini dari atas
        hit = None
        for z in live:
            if z[4] and L[i] <= z[1] < C[i - 1] and (hit is None or z[1] > hit[1]):
                hit = z
        if hit is None:
            continue
        live.remove(hit)
        if "rsi" in conf and not rs[i - 1] <= cfg.rsi_lv:
            continue
        if "chan" in conf and not (ch[i - 1] < 0):
            continue
        if "et" in conf:
            wait = (hit, i)
            continue
        entry = min(hit[1], O[i]) + cost
        open_at(i, entry, hit[3])
        if L[i] - xadj <= pos["sl"]:
            trades.append((pos, i, -cfg.sl, "SL"))
            pos = None

    return [{"time": pd.Timestamp(mk.t[p["i"]], tz="UTC"), "dir": "BUY" if is_buy else "SELL",
             "entry": round(sgn * p["entry"], 2), "zone": p["kind"], "pips": pips, "outcome": why,
             "exit_time": pd.Timestamp(mk.t[x], tz="UTC")} for p, x, pips, why in trades]


def stats(g: pd.DataFrame) -> dict:
    if g.empty:
        return {"n": 0, "wr%": 0, "pips": 0, "PF": 0, "DD": 0, "per_hari": 0}
    p = g.sort_values("time")["pips"]
    eq = p.cumsum()
    days = max(1, g.time.dt.date.nunique())
    gl = -p[p < 0].sum()
    return {"n": len(p), "wr%": round(100 * (p > 0).mean(), 1), "pips": round(p.sum()),
            "PF": round(p[p > 0].sum() / gl, 2) if gl else np.inf,
            "DD": round(float((eq.cummax() - eq).max())), "per_hari": round(len(p) / days, 1)}


def run(mk: Market, cfg: Cfg) -> pd.DataFrame:
    t = pd.DataFrame(run_side(mk, cfg, True) + run_side(mk, cfg, False))
    return t.sort_values("time").reset_index(drop=True) if not t.empty else t


def grid() -> list[Cfg]:
    out = []
    for zone, away, conf, ses in itertools.product(("swing", "poi"), (2.0, 4.0),
                                                   ("none", "rsi", "chan", "et", "rsi+chan", "chan+et"),
                                                   ("pagi", "all")):
        out.append(Cfg(zone, away, conf, 30.0, 30.0, 30.0, ses))
    # TP/SL alternatif pada beberapa kombinasi
    for conf in ("none", "chan", "et"):
        for tp, sl in ((30, 50), (50, 30), (20, 40)):
            out.append(Cfg("swing", 2.0, conf, 30.0, tp, sl, "pagi"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-06-16")
    args = ap.parse_args()
    df = load_m1("M1")
    df = df[df.index >= args.start]
    mk = Market(df)
    print(f"Data M1 {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d} ({mk.n} bar) | zona swing buy "
          f"{len(mk.zones[(True, 'swing')])}, poi buy {len(mk.zones[(True, 'poi')])}", flush=True)
    rows, allt = [], []
    for cfg in grid():
        t = run(mk, cfg)
        if t.empty:
            continue
        t["cfg"] = cfg.name
        allt.append(t)
        tr, te = stats(t[t.time < SPLIT]), stats(t[t.time >= SPLIT])
        rows.append({"cfg": cfg.name, **{f"tr_{k}": v for k, v in tr.items()},
                     **{f"te_{k}": v for k, v in te.items()}})
        print(f"  {cfg.name:<42} latih {tr} | uji {te}", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(settings.DATA_DIR / "dt_scalper_grid.csv", index=False)
    pd.concat(allt).to_csv(settings.DATA_DIR / "dt_scalper_trades.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_rows", 100):
        print("\nUrut PF uji:\n" + res.sort_values("te_PF", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
