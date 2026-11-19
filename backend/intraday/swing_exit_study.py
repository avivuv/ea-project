"""
Studi exit swing Donchian (entry & biaya SAMA dengan `intraday.swing` / runner `swing_live`).
Yang divariasikan hanya cara keluar. Semua varian tetap memakai SL awal 2 x ATR14 TF sinyal, tanpa TP
(kecuali partial), batas hold 60 hari.

  trK            chandelier: SL = ekstrem sejak entry - K x ATR (ATR saat entry)  ← aturan runner (K=3 / 4)
  trK_live       chandelier dengan ATR TF terbaru (bar TF terakhir yang sudah close)
  trK_aX         chandelier baru aktif setelah harga sempat +X R
  beX_trK        SL -> entry setelah sempat +X R, plus chandelier K
  donN           exit channel: SL = low terendah (buy) / high tertinggi (sell) N bar TF terakhir yang close
  emaN           tutup di open H1 berikutnya bila bar TF close di sisi berlawanan EMA N TF
  pX_trK         tutup 50% di +X R, sisa chandelier K

Urutan per bar H1 (konservatif, sama dengan swing.simulate): exit berbasis close TF di open bar, lalu cek SL,
lalu partial, lalu update stop (berlaku mulai bar berikutnya).

    python -m intraday.swing_exit_study
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from intraday import swing as sw

CONFIGS = [  # (id, simbol, nama variasi swing)
    ("XAU_D1_DON20", "XAUUSD", "DONCHIAN_D1_n20_SL2ATR_trail3_trD1"),
    ("XAU_H4_DON55", "XAUUSD", "DONCHIAN_H4_n55_SL2ATR_trail4_trD1"),
    ("BTC_H4_DON55", "BTCUSD", "DONCHIAN_H4_n55_SL2ATR_trail4_trD1"),
    ("JPY_H4_DON55", "USDJPY", "DONCHIAN_H4_n55_SL2ATR_trail4_trD1"),
]


def exits() -> dict[str, dict]:
    e: dict[str, dict] = {}
    for k in (2, 2.5, 3, 3.5, 4, 5, 6):
        e[f"tr{k:g}"] = {"trail": k}
    for k in (3, 4, 5, 6):
        e[f"tr{k}_live"] = {"trail": k, "live": True}
    for k in (2, 3, 4):
        for a in (1, 2):
            e[f"tr{k}_a{a}"] = {"trail": k, "act": a}
    for b in (0.5, 1, 2):
        for k in (3, 4, 5, 6):
            e[f"be{b:g}_tr{k}"] = {"trail": k, "be": b}
    for n in (5, 10, 20):
        e[f"don{n}"] = {"don": n}
    for n in (10, 20, 50):
        e[f"ema{n}"] = {"ema": n}
    for p in (1, 2):
        for k in (3, 4):
            e[f"p{p}_tr{k}"] = {"trail": k, "partial": p}
    return e


def tf_on_h1(h1: pd.DataFrame, b: pd.DataFrame, s: pd.Series, tf: str) -> np.ndarray:
    """Nilai seri TF yang berlaku di OPEN tiap bar H1 (bar TF terakhir yang sudah close)."""
    s = s.copy()
    s.index = b.index + pd.Timedelta(sw.RULES[tf])
    return s.reindex(h1.index, method="ffill").to_numpy(float)


def simulate(h1: pd.DataFrame, sig: pd.DataFrame, v: sw.V, spec: dict, aux: dict) -> pd.DataFrame:
    t = h1.index.values
    o, h, l, c = (h1[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    spr = np.maximum(h1["spread"].to_numpy(float), sw.MIN_SPREAD)
    slip = sw.SLIP
    nb = len(t)
    idx = np.searchsorted(t, sig.index.values.astype("datetime64[ns]"), side="left")
    K, act, be, part = spec.get("trail"), spec.get("act"), spec.get("be"), spec.get("partial")
    live = spec.get("live", False)
    don_lo = don_hi = ema_v = None
    if spec.get("don"):
        don_lo, don_hi = aux[f"donlo{spec['don']}"], aux[f"donhi{spec['don']}"]
    if spec.get("ema"):
        ema_v = aux[f"ema{spec['ema']}"]
    atr_o, cls_o = aux["atr"], aux["close"]
    rows, free_at = [], 0
    for i, dr, dist in zip(idx, sig.dir.to_numpy(), sig.sl_dist.to_numpy()):
        if i >= nb or i < free_at or dist <= 0:
            continue
        trail_fix = K / v.sl_atr * dist if K else None
        if dr > 0:
            entry = o[i] + spr[i] + slip
            sl, ext = entry - dist, h[i]
        else:
            entry = o[i] - slip
            sl, ext = entry + dist, l[i]
        end = min(nb, i + 24 * 60)
        exit_p, j, why, done_part, part_r = None, i, "TIME", False, 0.0
        tf_close0 = cls_o[i]                       # close bar TF sinyal (yang berlaku di bar entry)
        for j in range(i, end):
            # exit EMA: bar TF yang close setelah entry, close-nya di sisi berlawanan EMA
            if ema_v is not None and j > i and cls_o[j] != tf_close0 and not np.isnan(ema_v[j]):
                if dr * (cls_o[j] - ema_v[j]) < 0:
                    exit_p = o[j] - slip if dr > 0 else o[j] + spr[j] + slip
                    why = "EMA"; break
            if dr > 0:
                if l[j] <= sl:
                    exit_p, why = min(sl, o[j]) - slip, "SL"; break
                if part and not done_part and h[j] >= entry + part * dist:
                    done_part, part_r = True, part
                ext = max(ext, h[j])
                best = (ext - entry) / dist
            else:
                ah, ao = h[j] + spr[j], o[j] + spr[j]
                if ah >= sl:
                    exit_p, why = max(sl, ao) + slip, "SL"; break
                if part and not done_part and l[j] + spr[j] <= entry - part * dist:
                    done_part, part_r = True, part
                ext = min(ext, l[j])
                best = (entry - ext) / dist
            nj = min(j + 1, nb - 1)
            new = []
            if K and (act is None or best >= act):
                td = K * atr_o[nj] if live else trail_fix
                if td == td:
                    new.append(ext - td if dr > 0 else ext + td)
            if be is not None and best >= be:
                new.append(entry)
            if don_lo is not None:
                lv = don_lo[nj] if dr > 0 else don_hi[nj]
                if lv == lv:
                    new.append(lv)
            for lv in new:
                sl = max(sl, lv) if dr > 0 else min(sl, lv)
        if exit_p is None:
            exit_p = c[j] - slip if dr > 0 else c[j] + spr[j] + slip
        r = ((exit_p - entry) if dr > 0 else (entry - exit_p)) / dist
        if done_part:
            r = 0.5 * part_r + 0.5 * r
        rows.append({"time": pd.Timestamp(t[i], tz="UTC"), "dir": int(dr), "r": r, "why": why,
                     "hold_h": j - i + 1})
        free_at = j + 1
    return pd.DataFrame(rows)


def summarize(tr: pd.DataFrame) -> dict:
    r = tr.r.to_numpy()
    eq = np.cumsum(r)
    pf = lambda x: round(x[x > 0].sum() / -x[x < 0].sum(), 2) if (x < 0).any() else np.inf
    la, uj = tr[tr.time < sw.SPLIT].r.to_numpy(), tr[tr.time >= sw.SPLIT].r.to_numpy()
    yr = tr.groupby(tr.time.dt.year).r.sum()
    return {"n": len(r), "WR": round(100 * (r > 0).mean()), "PF": pf(r), "PF_latih": pf(la), "PF_uji": pf(uj),
            "avgR": round(r.mean(), 3), "totR": round(r.sum(), 1),
            "DD_R": round((np.maximum.accumulate(eq) - eq).max(), 1),
            "latih_avgR": round(la.mean(), 3), "uji_avgR": round(uj.mean(), 3),
            "thn+": f"{(yr > 0).sum()}/{len(yr)}", "hold_hari": round(tr.hold_h.mean() / 24, 1)}


def main() -> None:
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 200)
    cache: dict[str, tuple] = {}
    allrows = []
    for mid, sym, vname in CONFIGS:
        if sym not in cache:
            h1 = sw.load_h1(sym)
            cache[sym] = (h1, sw.d1_trend_series(h1), sw.MIN_SPREAD, sw.SLIP)
        h1, d1t, sw.MIN_SPREAD, sw.SLIP = cache[sym]
        v = {x.name: x for x in sw.variants()}[vname]
        sig = sw.signals(h1, v, d1t)
        b = sw.resample(h1, v.tf)
        aux = {"atr": tf_on_h1(h1, b, sw.atr(b), v.tf), "close": tf_on_h1(h1, b, b.close, v.tf)}
        for n in (5, 10, 20):
            aux[f"donlo{n}"] = tf_on_h1(h1, b, b.low.rolling(n).min(), v.tf)
            aux[f"donhi{n}"] = tf_on_h1(h1, b, b.high.rolling(n).max(), v.tf)
        for n in (10, 20, 50):
            aux[f"ema{n}"] = tf_on_h1(h1, b, sw.ema(b.close, n), v.tf)
        live_ex = "tr" + vname.split("_trail")[1].split("_")[0]
        rows = []
        for name, spec in exits().items():
            tr = simulate(h1, sig, v, spec, aux)
            rows.append({"exit": name + (" *" if name == live_ex else ""), **summarize(tr)})
        res = pd.DataFrame(rows).sort_values("avgR", ascending=False)
        res.insert(0, "metode", mid)
        allrows.append(res)
        print(f"\n== {mid} ({vname}) — * = aturan runner sekarang; latih < {sw.SPLIT:%Y}, uji >=")
        print(res.drop(columns="metode").to_string(index=False), flush=True)
    out = pd.concat(allrows)
    out.to_csv(sw.settings.DATA_DIR / "swing_exit_study.csv", index=False)


if __name__ == "__main__":
    main()
