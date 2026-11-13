"""
Backtest aturan gabungan MARKET vs POI, diputuskan saat sinyal masuk.

    python -m tg_signal.hybrid_backtest

Keputusan per sinyal (ruang BUY; SELL dinegasikan), memakai bar M1 yang sudah close sebelum sinyal:
  dist = open bar pertama setelah sinyal − ZERO   (> 0: harga belum sampai zona)
  A. 0 < dist ≤ D  dan ada momentum searah  → MARKET
  B. dist ≤ 0 (sudah di zona)               → inzone=poi: limit POI (tanpa POI aktif → MARKET)
                                               inzone=market: MARKET
  C/D. lainnya                               → limit POI terdekat (tepi atas), SL 30, hangus X pips
Momentum searah di N bar terakhir:
  body : ada candle searah dengan body ≥ 1 × ATR14 (rata-rata high−low)
  fvg  : terbentuk FVG searah
  bos  : close tertinggi di N bar > high tertinggi 20 bar sebelumnya
  any  : salah satu di atas
Parameter dipilih di data latih (Agu–Sep), diuji di Okt–Nov. TP = SL = 30 pips.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal.backtest_tg import Bars, Variant, load_signals, simulate
from tg_signal.detectors.poi import active_pois
from tg_signal.market_data import load_m1
from tg_signal.poi_backtest import MAX_AGE, TOL, PoiVariant, Space, sim_poi
from tg_signal.price_resolver import resolve_zone
from tg_signal.store import Store

SPLIT = pd.Timestamp("2026-10-01", tz="UTC")
FILLED = ("TP", "SL", "TIMEOUT")


def features(sig, bars: Bars, sp: Space) -> dict | None:
    s = bars.first_bar_after(sig.time)
    if s < 40 or s >= bars.n:
        return None
    zone = resolve_zone(sig.direction, sig.level_first, sig.level_last, ref=bars.o[s - 1])
    is_buy = sig.direction == "BUY"
    sgn = 1 if is_buy else -1
    O, H, L, C = sp.arr[is_buy]
    zero, last = sgn * zone.zero, sgn * zone.last
    atr = float(np.mean(H[s - 14:s] - L[s - 14:s]))
    f = {"msg_id": sig.msg_id, "time": sig.time, "dist": O[s] - zero}
    for n in (3, 5):
        w = range(s - n, s)
        body = any(C[i] - O[i] >= atr for i in w)
        fvg = any(L[i] > H[i - 2] for i in w)
        bos = C[s - n:s].max() > H[s - n - 20:s - n].max()
        f.update({f"body{n}": body, f"fvg{n}": fvg, f"bos{n}": bos, f"any{n}": body or fvg or bos})
    f["has_poi"] = bool(active_pois([p for p in sp.pois[is_buy] if last - TOL <= p.top <= zero + TOL],
                                    s, last - TOL, zero + TOL, MAX_AGE))
    return f


def stats(pips: pd.Series) -> dict:
    pips = pips.dropna()
    gw, gl = pips[pips > 0].sum(), -pips[pips < 0].sum()
    return {"trades": len(pips), "wr%": round(100 * (pips > 0).mean(), 1) if len(pips) else 0.0,
            "pips": round(pips.sum(), 0), "PF": round(gw / gl, 2) if gl else np.inf}


def main() -> None:
    df = load_m1("M1")
    start, end = df.index[0].to_pydatetime(), df.index[-1].to_pydatetime()
    signals = load_signals(Store(settings.DB_PATH), start, end)
    bars = Bars(df)
    sp = Space(bars)
    print(f"Sinyal: {len(signals)} | {start:%Y-%m-%d} → {end:%Y-%m-%d}")

    mk = Variant("MARKET", 1, 30, "entry")
    pv = {x: PoiVariant("LIMIT", "fix", 30, "near", "top", x) for x in (10, 30)}
    rows = []
    for sg in signals:
        f = features(sg, bars, sp)
        if f is None:
            continue
        m = simulate(sg, mk, bars)
        f["mkt"] = m["pips"] if m["outcome"] in FILLED else np.nan
        for x, v in pv.items():
            r = sim_poi(sg, v, bars, sp)
            f[f"poi{x}"] = r["pips"] if r["outcome"] in FILLED else np.nan
        rows.append(f)
    d = pd.DataFrame(rows)
    d["time"] = pd.to_datetime(d["time"], utc=True)
    d.to_csv(settings.DATA_DIR / "hybrid_features.csv", index=False)

    base = {"MARKET": d["mkt"], "POI_X10": d["poi10"], "POI_X30": d["poi30"]}
    out = []
    for name, s in base.items():
        out.append({"rule": name, **{f"tr_{k}": v for k, v in stats(s[d.time < SPLIT]).items()},
                    **{f"te_{k}": v for k, v in stats(s[d.time >= SPLIT]).items()}})
    for D, mom, n, inzone, x in itertools.product((1, 2, 3), ("body", "fvg", "bos", "any"), (3, 5),
                                                  ("poi", "market"), (10, 30)):
        a = (d.dist > 0) & (d.dist <= D) & d[f"{mom}{n}"]
        inz = d.dist <= 0
        use_mkt = a | (inz & ((inzone == "market") | ~d.has_poi))
        pips = d[f"poi{x}"].where(~use_mkt, d["mkt"])
        out.append({"rule": f"D{D}_{mom}{n}_in{inzone}_X{x}",
                    "pctA": round(100 * a.mean(), 1),
                    **{f"tr_{k}": v for k, v in stats(pips[d.time < SPLIT]).items()},
                    **{f"te_{k}": v for k, v in stats(pips[d.time >= SPLIT]).items()}})
    res = pd.DataFrame(out)
    res.to_csv(settings.DATA_DIR / "hybrid_grid.csv", index=False)
    with pd.option_context("display.width", 220, "display.max_rows", 60):
        print("\nPembanding:")
        print(res.head(3).drop(columns="pctA").to_string(index=False))
        print("\n15 aturan terbaik di data LATIH (Agu–Sep, PF, min 300 trade) + hasilnya di UJI (Okt–Nov):")
        g = res.iloc[3:]
        print(g[g.tr_trades >= 300].sort_values("tr_PF", ascending=False).head(15).to_string(index=False))
        print("\nPositif di LATIH dan UJI:")
        print(g[(g.tr_PF > 1) & (g.te_PF > 1)].to_string(index=False) or "(tidak ada)")


if __name__ == "__main__":
    main()
