"""
Studi: posisi mode POI belum TP, tapi admin sudah bilang "tp". Apa yang sebaiknya dilakukan?
Pemicu dibandingkan:
  harga : harga sampai ZERO ± 10 pips (TP provider versi ZERO)
  pesan : pesan admin berisi "tp" (tp, hit tp, mid tp, last tp, done tp, ...) — dikaitkan ke sinyal
          terakhir sebelum pesan itu (maks 3 jam). "zero"/"mid"/"last" saja = info kedalaman, bukan TP.
Tindakan saat pemicu (trade yang sama, jalur bar M1):
  A. dibiarkan (TP 30 / SL 30) · B. TP → entry + 20 pips (harga sudah lewat → tutup di +20) ·
  C. SL → BE · D. TP +20 & SL BE · E. tutup langsung

    python -m tg_signal.admin_tp_study
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal.backtest_tg import Bars, load_signals
from tg_signal.market_data import load_m1
from tg_signal.poi_backtest import PoiVariant, Space, sim_poi
from tg_signal.price_resolver import resolve_zone
from tg_signal.store import Store

PIP = settings.PIP_SIZE
ADMIN_TP_PIPS = settings.TG_EXPIRE_TP_PIPS
V = PoiVariant("LIMIT", "fix", 30, "near", "top", 30)
TP_MSG = re.compile(r"\btp\b", re.I)
SL_MSG = re.compile(r"\bsl\b", re.I)


def admin_tp_times(store: Store, signals) -> dict[int, pd.Timestamp]:
    """msg_id sinyal → waktu pesan 'tp' pertama setelahnya (sebelum sinyal berikutnya, maks 3 jam)."""
    msgs = store.conn.execute("SELECT date_utc, text FROM messages WHERE kind='OTHER' AND length(text) <= 30"
                              " ORDER BY date_utc").fetchall()
    tps = [pd.Timestamp(m["date_utc"]).tz_convert("UTC") for m in msgs
           if TP_MSG.search(m["text"]) and not SL_MSG.search(m["text"])]
    tps = pd.DatetimeIndex(tps)
    out = {}
    for i, sg in enumerate(signals):
        t0 = pd.Timestamp(sg.time)
        t1 = pd.Timestamp(signals[i + 1].time) if i + 1 < len(signals) else t0 + pd.Timedelta(hours=3)
        t1 = min(t1, t0 + pd.Timedelta(hours=3))
        k = tps.searchsorted(t0, side="right")
        if k < len(tps) and tps[k] < t1:
            out[sg.msg_id] = tps[k]
    return out


def walk(O, H, L, C, spr, is_buy, k0, entry, trig, mode, n):
    """trig: ('price', level) atau ('bar', indeks bar M1 pesan admin)."""
    sl, tp = entry - 3.0, entry + 3.0
    hit = False
    end = min(n, k0 + 2 * 1440)
    for j in range(k0 + 1, end):
        xadj = 0.0 if is_buy else spr[j]
        lo, hi = L[j] - xadj, H[j] - xadj
        if lo <= sl:
            return (sl - entry) / PIP, hit
        if hi >= tp:
            return (tp - entry) / PIP, hit
        now = (H[j] >= trig[1]) if trig[0] == "price" else (j >= trig[1])
        if not hit and now and mode != "A":
            hit = True
            # harga saat pemicu: level TP admin (live cek tiap 5 dtk) / open bar pertama setelah pesan
            ref = (trig[1] if trig[0] == "price" else O[j]) - xadj
            if trig[0] == "bar" and lo <= sl:
                return (sl - entry) / PIP, True
            if mode == "E":
                return (ref - entry) / PIP, True
            if mode in ("B", "D"):
                tp = entry + 2.0
                if ref >= tp:
                    return (ref - entry) / PIP, True
                if hi >= tp:                    # di bar yang sama harga lanjut naik melewati TP baru
                    return 20.0, True
            if mode in ("C", "D"):
                sl = max(sl, entry)
    return (C[end - 1] - entry) / PIP, hit


def main() -> None:
    df = load_m1("M1")
    bars = Bars(df)
    sp = Space(bars)
    store = Store(settings.DB_PATH)
    sigs = load_signals(store, df.index[0].to_pydatetime(), df.index[-1].to_pydatetime())
    tp_at = admin_tp_times(store, sigs)
    print(f"Sinyal {len(sigs)} | yang diikuti pesan 'tp' admin: {len(tp_at)}")
    rows = []
    for sg in sigs:
        r = sim_poi(sg, V, bars, sp)
        if r["outcome"] not in ("TP", "SL", "TIMEOUT"):
            continue
        is_buy = sg.direction == "BUY"
        g = 1 if is_buy else -1
        s = bars.first_bar_after(sg.time)
        z = resolve_zone(sg.direction, sg.level_first, sg.level_last, ref=bars.o[s - 1])
        O, H, L, C = sp.arr[is_buy]
        k0 = int(np.searchsorted(bars.t, np.datetime64(r["entry_time"].tz_convert(None)), side="left"))
        entry = g * r["entry"]
        row = {"time": sg.time}
        price_trig = ("price", g * z.zero + ADMIN_TP_PIPS * PIP)
        t_msg = tp_at.get(sg.msg_id)
        msg_trig = ("bar", int(np.searchsorted(bars.t, np.datetime64(t_msg.tz_convert(None)), side="right"))
                    if t_msg is not None else 10 ** 12)
        for m in "ABCDE":
            row[f"harga_{m}"], _ = walk(O, H, L, C, bars.spr, is_buy, k0, entry, price_trig, m, bars.n)
            row[f"pesan_{m}"], row["msg_hit"] = walk(O, H, L, C, bars.spr, is_buy, k0, entry, msg_trig, m, bars.n)
        rows.append(row)
    d = pd.DataFrame(rows)
    d["per"] = np.where(pd.to_datetime(d.time, utc=True) < pd.Timestamp("2026-10-01", tz="UTC"), "Agu-Sep", "Okt-Nov")
    names = {"A": "dibiarkan (TP30/SL30)", "B": "TP jadi +20", "C": "SL ke BE", "D": "TP +20 & SL BE",
             "E": "tutup langsung"}
    hit = d[d.msg_hit]
    print(f"Trade POI: {len(d)} | pesan 'tp' datang saat posisi masih terbuka: {len(hit)} "
          f"({100 * len(hit) / len(d):.0f}%) → bila dibiarkan: TP {100 * (hit.harga_A > 0).mean():.0f}% · "
          f"SL {100 * (hit.harga_A < 0).mean():.0f}%")
    for trig in ("harga", "pesan"):
        print(f"\nPemicu: {trig}")
        for m, nm in names.items():
            if trig == "pesan" and m == "A":
                continue
            out = []
            for per in ("Agu-Sep", "Okt-Nov"):
                x = d.loc[d.per == per, f"{trig}_{m}"]
                gw, gl = x[x > 0].sum(), -x[x < 0].sum()
                out.append(f"{per}: WR {100 * (x > 0).mean():3.0f}% pips {x.sum():+6.0f} PF {gw / gl:.2f}")
            print(f"  {nm:<24} " + " | ".join(out))


if __name__ == "__main__":
    main()
