"""
Backtest entry di POI (FVG / OB / IFVG M1) yang berada di dalam zona sinyal, dibanding mode yang ada.

    python -m tg_signal.poi_backtest --today          # sinyal hari ini (WIB), tabel per sinyal
    python -m tg_signal.poi_backtest                  # seluruh data M1 di cache

Mode POI:
- POI_LIMIT : pending limit di tepi atas (proximal) POI aktif yang tepi atasnya berada di zona
              [LAST − tol, ZERO + tol]. POI gagal (close menembus) → pindah ke POI berikutnya.
- POI_CONF  : tunggu harga menyentuh POI, lalu konfirmasi M1 resep ADMIN (rejection 61,8% /
              engulfing / OBIM) dengan POI sebagai lokasi → entry market di open bar berikutnya.
SL: "poi" = di bawah POI − buffer (jarak dibatasi 10–30 pips) | "fix" = 30 pips dari entry.
TP: tetap dalam pips dari entry. Asumsi harga/spread/hangus sama dengan backtest_tg.py.
Setiap sinyal disimulasikan independen (tanpa batas posisi / target harian).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal.backtest_tg import Bars, Variant, load_signals, simulate, summarize
from tg_signal.confirmation import confirmed
from tg_signal.detectors.poi import active_pois, find_pois
from tg_signal.market_data import load_m1
from tg_signal.price_resolver import resolve_zone
from tg_signal.store import Store

PIP = settings.PIP_SIZE
HORIZON = 2 * 1440
MAX_AGE = 240           # umur maksimum POI (bar M1)
TOL = 0.5               # zona diperlebar $0.5 untuk mencari POI yang beririsan
SL_BUF = 0.5            # SL $0.5 di bawah POI
SL_MIN, SL_MAX = 1.0, 3.0


@dataclass(frozen=True)
class PoiVariant:
    mode: str           # LIMIT | CONF
    sl: str             # poi | fix
    tp_pips: float
    pick: str = "near"  # near: POI teratas (disentuh duluan) | deep: POI terdalam yang masih utuh
    lvl: str = "top"    # LIMIT: top = tepi atas POI | third = sepertiga bawah POI
    exp_pips: float = settings.TG_EXPIRE_TP_PIPS   # hangus bila harga sampai ZERO + ini sebelum entry

    @property
    def name(self) -> str:
        lv = f"_{self.lvl}" if self.mode == "LIMIT" else ""
        return f"POI_{self.mode}_{self.pick}{lv}_TP{self.tp_pips:g}_SL{self.sl}_X{self.exp_pips:g}"

    def choose(self, act):
        return max(act, key=lambda z: z.top) if self.pick == "near" else min(act, key=lambda z: z.bottom)

    def level(self, p) -> float:
        return p.top if self.lvl == "top" else p.bottom + (p.top - p.bottom) / 3


class Space:
    """Array global ruang BUY / SELL + POI-nya (dihitung sekali)."""

    def __init__(self, bars: Bars):
        self.arr = {True: (bars.o, bars.h, bars.l, bars.c),
                    False: (-bars.o, -bars.l, -bars.h, -bars.c)}
        self.pois = {k: find_pois(*v) for k, v in self.arr.items()}


def _sl(entry: float, bottom: float, mode: str) -> float:
    if mode == "fix":
        return entry - SL_MAX
    dist = min(SL_MAX, max(SL_MIN, entry - (bottom - SL_BUF)))
    return entry - dist


def sim_poi(sig, v: PoiVariant, bars: Bars, sp: Space) -> dict:
    res = {"time": sig.time, "msg_id": sig.msg_id, "direction": sig.direction, "variant": v.name,
           "outcome": "", "pips": 0.0, "entry_time": None, "entry": None, "poi": ""}
    s = bars.first_bar_after(sig.time)
    if s <= 0 or s >= bars.n:
        res["outcome"] = "NO_DATA"
        return res
    zone = resolve_zone(sig.direction, sig.level_first, sig.level_last, ref=bars.o[s - 1])
    if zone.distance > settings.TG_MAX_ZONE_DISTANCE:
        res["outcome"] = "REJECTED_DISTANCE"
        return res
    is_buy = sig.direction == "BUY"
    sgn = 1 if is_buy else -1
    O, H, L, C = sp.arr[is_buy]
    spr = bars.spr
    zero, last = sgn * zone.zero, sgn * zone.last
    lo, hi = last - TOL, zero + TOL
    end = min(bars.n, s + HORIZON)
    cands = [p for p in sp.pois[is_buy]
             if s - MAX_AGE <= p.created < end and lo <= p.top <= hi]   # tepi atas POI di dalam zona
    exp_tp = zero + v.exp_pips * PIP
    exp_sl = last - sig.sl_pips * PIP
    tp_dist = v.tp_pips * PIP

    touched = False
    armed = None
    low_since = np.inf
    pos = None          # (bar masuk, entry, sl, tp, fill_bar_skip)
    for j in range(s, end):
        cost = spr[j] if is_buy else 0.0
        xadj = 0.0 if is_buy else spr[j]
        if pos is None:
            if not touched and L[j] + cost <= zero:
                touched = True
            act = active_pois(cands, j, lo, hi, MAX_AGE)
            if v.mode == "LIMIT":
                if act:
                    p = v.choose(act)
                    px = v.level(p)
                    if L[j] + cost <= px:
                        entry = min(px, O[j] + cost)
                        sl = _sl(entry, p.bottom, v.sl)
                        pos = (j, entry, sl, entry + tp_dist, True)
                        res["poi"] = p.kind
                        if L[j] - xadj <= sl:
                            return _done(res, bars, pos, j, sgn, (sl - entry) / PIP, "SL")
                        continue
                if touched and H[j] >= exp_tp:
                    res["outcome"] = "EXPIRED_TP"
                    return res
                if touched and L[j] <= exp_sl:
                    res["outcome"] = "EXPIRED_SL"
                    return res
                continue
            # CONF
            if touched and H[j] >= exp_tp:
                res["outcome"] = "EXPIRED_TP"
                return res
            if touched and L[j] <= exp_sl:
                res["outcome"] = "EXPIRED_SL"
                return res
            if armed is not None and (armed.dead < j or C[j] < armed.bottom):
                armed = None                    # POI gagal → cari POI berikutnya
            if armed is None and act:
                p = v.choose(act)
                if L[j] <= p.top:
                    armed, low_since = p, np.inf
            if armed is not None:
                low_since = min(low_since, L[j])
                if j + 1 < end and confirmed("ADMIN", "BUY", O, H, L, C, j, armed.top, 0.3):
                    k = j + 1
                    entry = O[k] + (spr[k] if is_buy else 0.0)
                    sl = _sl(entry, min(armed.bottom, low_since), v.sl)
                    pos = (k, entry, sl, entry + tp_dist, False)
                    res["poi"] = armed.kind
            continue

        k0, entry, sl, tp, skip_fill_bar = pos
        if j < k0 or (j == k0 and skip_fill_bar):
            continue
        if L[j] - xadj <= sl:
            return _done(res, bars, pos, j, sgn, (sl - entry) / PIP, "SL")
        if H[j] - xadj >= tp:
            return _done(res, bars, pos, j, sgn, v.tp_pips, "TP")

    if pos is None:
        res["outcome"] = "NOT_TOUCHED" if not touched else "OPEN_END"
        return res
    last_exit = C[end - 1] - (0.0 if is_buy else spr[end - 1])
    return _done(res, bars, pos, end - 1, sgn, (last_exit - pos[1]) / PIP, "TIMEOUT")


def _done(res, bars, pos, exit_j, sgn, pips, outcome) -> dict:
    res["outcome"], res["pips"] = outcome, round(pips, 1)
    res["entry"] = round(sgn * pos[1], 2)
    res["entry_time"] = pd.Timestamp(bars.t[pos[0]], tz="UTC")
    res["exit_time"] = pd.Timestamp(bars.t[exit_j], tz="UTC")
    return res


BASELINES = [Variant("MARKET", 1, 30, "entry"),      # default live sekarang
             Variant("ZERO", 1, 30, "zone"),          # TG_ENTRY_MODE=ZONE
             Variant("ADMIN", 1, 30, "entry")]        # konfirmasi resep admin di ZERO
POI_VARIANTS = ([PoiVariant("LIMIT", sl, tp, pick, lvl, x) for x in (10, 30) for pick in ("near", "deep")
                 for lvl in ("top", "third") for sl in ("poi", "fix") for tp in (20, 30)]
                + [PoiVariant("CONF", sl, tp, pick, "top", x) for x in (10, 30) for pick in ("near", "deep")
                   for sl in ("poi", "fix") for tp in (20, 30)])


def run(signals, bars: Bars) -> pd.DataFrame:
    sp = Space(bars)
    rows = [simulate(sg, v, bars) for v in BASELINES for sg in signals]
    rows += [sim_poi(sg, v, bars, sp) for v in POI_VARIANTS for sg in signals]
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


def per_signal_table(df: pd.DataFrame, signals) -> str:
    show = ["MARKET_TP30_SLentry", "LIMIT_ZERO_TP30_SLzone", "ADMIN_M1_TP30_SLentry",
            "POI_LIMIT_near_top_TP30_SLfix_X30", "POI_LIMIT_deep_top_TP30_SLfix_X30",
            "POI_LIMIT_deep_third_TP30_SLfix_X30"]
    short = {"MARKET_TP30_SLentry": "MARKET", "LIMIT_ZERO_TP30_SLzone": "ZONE",
             "ADMIN_M1_TP30_SLentry": "ADMIN", "POI_LIMIT_near_top_TP30_SLfix_X30": "NEAR_TOP x30",
             "POI_LIMIT_deep_top_TP30_SLfix_X30": "DEEP_TOP x30",
             "POI_LIMIT_deep_third_TP30_SLfix_X30": "DEEP_3RD x30"}
    lines = []
    for sg in signals:
        g = df[df["msg_id"] == sg.msg_id].set_index("variant")
        wib = (sg.time + timedelta(hours=7)).strftime("%H:%M")
        z = g.loc["MARKET_TP30_SLentry"]
        cells = []
        for name in show:
            r = g.loc[name]
            o = r["outcome"]
            if o in ("TP", "SL", "TIMEOUT", "OPEN_END"):
                extra = ""
                if name.startswith("POI") and r.get("entry") is not None and not pd.isna(r.get("entry")):
                    extra = f"@{r['entry']:.2f}{r['poi'][:1]}"
                cells.append(f"{o}{r['pips']:+.0f}{extra}")
            else:
                cells.append(o.replace("EXPIRED_", "EXP_").replace("NOT_TOUCHED", "-"))
        lines.append(f"{wib} {sg.direction:4} {sg.level_first:02d}-{sg.level_last:02d} "
                     f"({z['zero']:.0f}/{z['last']:.0f}) | " + " | ".join(f"{c:<16}" for c in cells))
    header = "WIB   arah  sinyal (zona)        | " + " | ".join(f"{short[s]:<16}" for s in show)
    return header + "\n" + "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest entry di POI dalam zona sinyal")
    ap.add_argument("--today", action="store_true", help="hanya sinyal hari ini (WIB)")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    df = load_m1("M1")
    start, end = df.index[0].to_pydatetime(), df.index[-1].to_pydatetime()
    if args.today:
        now_wib = datetime.now(timezone.utc) + timedelta(hours=7)
        start = datetime(now_wib.year, now_wib.month, now_wib.day, tzinfo=timezone.utc) - timedelta(hours=7)
    if args.start:
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    if args.end:
        end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    df = df[(df.index >= start - timedelta(hours=6)) & (df.index <= end + timedelta(days=2))]
    signals = load_signals(Store(settings.DB_PATH), start, end)
    print(f"Sinyal unik {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC: {len(signals)} "
          f"| bar M1 terakhir {df.index[-1]:%Y-%m-%d %H:%M} UTC")
    bars = Bars(df)
    res = run(signals, bars)
    if args.today:
        print(per_signal_table(res, signals))
        print("Keterangan: @harga + jenis POI (F=FVG, O=OB, I=IFVG); EXP_TP = sinyal selesai TP sebelum kita masuk\n")
    with pd.option_context("display.width", 220, "display.max_columns", 30):
        print(summarize(res).to_string(index=False))
    out = settings.DATA_DIR / ("poi_backtest_today.csv" if args.today else "poi_backtest.csv")
    res.to_csv(out, index=False)
    print(f"\nDisimpan: {out}")


if __name__ == "__main__":
    main()
