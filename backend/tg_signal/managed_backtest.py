"""
Verifikasi sistem "TG Signal Layer" (folder CT Tele): entry pending di ZERO / market bila harga sudah
di dalam zona, SL dari ujung zona (LAST ± SL), kunci profit (+10 → SL +5) dan trailing.

    python -m tg_signal.managed_backtest                     # spread asli Exness per bar
    python -m tg_signal.managed_backtest --spread-pips 0.8   # asumsi spread di panduan CT Tele

Simulasi per sinyal secara independen di bar M1 (Agu–Nov 2026), konservatif:
- dalam satu bar: cek SL (SL yang berlaku saat bar dibuka) → cek TP → baru perbarui kunci/trailing
  memakai harga terbaik bar itu (berlaku mulai bar berikutnya).
- bar fill limit: hanya cek SL.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tg_signal import backtest_tg as bt
from tg_signal import settings
from tg_signal.price_resolver import resolve_zone
from tg_signal.store import Store

PIP = settings.PIP_SIZE


@dataclass(frozen=True)
class Mgmt:
    name: str
    tp: float = 30            # pips
    be_start: float = 10      # 0 = tanpa kunci
    be_lock: float = 5
    trail_start: float = 15   # 0 = tanpa trailing
    trail_lock: float = 10
    trail_step: float = 5
    sl_from_zone: bool = True
    sl: float = 30
    pending_min: int = 60
    zone_tol: float = 5


VARIANTS = [
    Mgmt("Akun1 TP30 kunci+trail", 30, 10, 5, 15, 10, 5),
    Mgmt("Akun2 TP100 kunci+trail40", 100, 10, 5, 40, 20, 20),
    Mgmt("TP30 tanpa kunci (pembanding)", 30, 0, 0, 0, 0, 0),
    Mgmt("TP100 tanpa kunci (pembanding)", 100, 0, 0, 0, 0, 0),
    Mgmt("Akun1, SL 30 dari entry", 30, 10, 5, 15, 10, 5, sl_from_zone=False),
    Mgmt("Hanya kunci +10→+5, TP30", 30, 10, 5, 0, 0, 0),
]


def lock_level(profit: float, m: Mgmt) -> float | None:
    if m.trail_start and profit >= m.trail_start:
        return m.trail_lock + np.floor((profit - m.trail_start) / m.trail_step) * m.trail_step
    if m.be_start and profit >= m.be_start:
        return m.be_lock
    return None


def simulate(sig: bt.Signal, m: Mgmt, b: bt.Bars) -> dict:
    s = b.first_bar_after(sig.time)
    if s <= 0 or s >= b.n:
        return {"outcome": "NO_DATA"}
    ref = b.o[s - 1]
    z = resolve_zone(sig.direction, sig.level_first, sig.level_last, ref=ref)
    if z.distance > 20:
        return {"outcome": "FAR"}
    end = min(b.n, s + 2 * 1440)
    o, h, l, c, spr, is_buy = bt._space(b, sig.direction, s, end)
    g = 1 if is_buy else -1
    zero, last = g * z.zero, g * z.last
    tol = m.zone_tol * PIP
    # posisi harga saat sinyal (ruang BUY): ask saat ini
    ask0 = o[0] + (spr[0] if is_buy else 0.0)
    if ask0 < last - tol:
        return {"outcome": "SKIP_BEYOND_LAST"}
    entry_i, entry = None, 0.0
    if ask0 <= zero:                          # sudah di dalam zona → market
        entry_i, entry = 0, ask0
    else:                                     # pending limit di ZERO
        for j in range(min(len(o), m.pending_min)):
            fc = spr[j] if is_buy else 0.0
            if l[j] + fc <= zero:
                entry_i, entry = j, min(zero, o[j] + fc)
                break
        if entry_i is None:
            return {"outcome": "PENDING_EXPIRED"}
    sl = (last if m.sl_from_zone else entry) - m.sl * PIP
    sl = min(sl, entry - m.sl * PIP) if not m.sl_from_zone else sl
    tp = entry + m.tp * PIP
    limit_fill = not (entry_i == 0 and ask0 <= zero)
    for j in range(entry_i, len(o)):
        xa = 0.0 if is_buy else spr[j]       # SELL keluar di ask
        lo, hi, op = l[j] - xa, h[j] - xa, o[j] - xa
        if lo <= sl:
            px = min(sl, op) if j > entry_i else sl      # gap melewati SL → keluar di open
            return {"outcome": "SL" if px < entry else "LOCK", "pips": (px - entry) / PIP}
        fill_bar = j == entry_i and limit_fill
        if hi >= tp and not fill_bar:
            return {"outcome": "TP", "pips": m.tp}
        if fill_bar:
            continue                                   # high bar fill bisa terjadi sebelum entry
        lk = lock_level((hi - entry) / PIP, m)
        if lk is not None:
            sl = max(sl, entry + lk * PIP)
    return {"outcome": "TIMEOUT", "pips": (c[-1] - (0 if is_buy else spr[-1]) - entry) / PIP}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spread-pips", type=float, default=None)
    a = ap.parse_args()
    df = bt.load_m1("M1")
    if a.spread_pips is not None:
        df = df.copy()
        df["spread"] = a.spread_pips * PIP
    b = bt.Bars(df)
    store = Store(settings.DB_PATH)
    sigs = bt.load_signals(store, df.index[0].to_pydatetime(), df.index[-1].to_pydatetime())
    split = pd.Timestamp("2026-09-24", tz="UTC")   # dua paruh ±sama panjang
    print(f"Spread: {'asli per bar (median %.1f pips)' % (df.spread.median() / PIP) if a.spread_pips is None else a.spread_pips}"
          f" | sinyal {len(sigs)} | Agu–Nov 2026 | USD @0.01 lot per sinyal")
    rows = []
    for m in VARIANTS:
        res = pd.DataFrame([{"time": pd.Timestamp(sg.time), **simulate(sg, m, b)} for sg in sigs])
        f = res.dropna(subset=["pips"])
        h1, h2 = f[f.time < split], f[f.time >= split]
        eq = f.pips.cumsum() * settings.USD_PER_PIP_001
        rows.append({
            "variasi": m.name, "trade": len(f), "WR%": round(100 * (f.pips > 0).mean(), 1),
            "avg_pips": round(f.pips.mean(), 2), "USD_total": round(f.pips.sum() * 0.1, 1),
            "USD_paruh1": round(h1.pips.sum() * 0.1, 1), "USD_paruh2": round(h2.pips.sum() * 0.1, 1),
            "maxDD_USD": round(float((eq.cummax() - eq).max()), 1),
            "hasil": res.outcome.value_counts().to_dict(),
        })
    with pd.option_context("display.width", 250, "display.max_colwidth", 120):
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
