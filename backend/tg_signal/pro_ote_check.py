"""
Uji tambahan zona OTE (fib 0.618–0.79 leg impuls) ke SMC Top-Down (pro_strategy), konfigurasi live.

    python -m tg_signal.pro_ote_check

Konfigurasi dasar = pro_live: M5, bias EMA50 H1 slope > 0.1 ATR, POI M15, entry FVG, RR3.
Variasi daftar POI (logika run_side tidak diubah):
  base        : POI M15 biasa (FVG/OB/IFVG)
  add_<tf>    : POI + zona OTE dari leg impuls <tf>
  only_<tf>   : hanya zona OTE
  inside_<tf> : hanya irisan POI ∩ zona OTE (POI yang berada di area OTE), aktif selama keduanya hidup
Zona OTE: swing low → swing high (fractal ±2) terkonfirmasi, leg ≥ $3 (M15) / $5 (H1);
mati saat close <tf> di bawah tepi 0.79 atau leg baru terbentuk.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tg_signal import pro_strategy as ps
from tg_signal.ote_strategy import _ote_m15
from tg_signal import ote_strategy as ots
from tg_signal.market_data import load_m1
from tg_signal.pro_live import BIAS_TF, CFG, EMA_SPAN, MIN_SLOPE

LEG_MIN = {15: 3.0, 60: 5.0}


def ote_zones(mk: ps.Market, is_buy: bool, minutes: int) -> list[tuple]:
    """Zona OTE dalam format POI pro_strategy: (created_m5, dead_m5, top, bottom, 'OTE')."""
    bars = mk.df.resample(f"{minutes}min").agg({"open": "first", "high": "max", "low": "min",
                                                 "close": "last"}).dropna()
    h, l, c = (bars[k].to_numpy(float) for k in ("high", "low", "close"))
    if not is_buy:
        h, l, c = -l, -h, -c
    old = ots.LEG_MIN
    ots.LEG_MIN = LEG_MIN[minutes]
    z = _ote_m15(h, l, c)
    ots.LEG_MIN = old
    to5 = np.searchsorted(mk.t, (bars.index + pd.Timedelta(minutes=minutes)).values.astype("datetime64[ns]"),
                          side="left") - 1
    out, n = [], len(c)
    k = 0
    while k < n:
        if not np.isfinite(z[k, 0]):
            k += 1
            continue
        leg, top, bot = z[k, 4], z[k, 0], z[k, 1]
        k1 = k + 1
        while k1 < n and z[k1, 4] == leg and c[k1] >= bot:
            k1 += 1
        out.append((int(to5[k]), int(to5[k1]) if k1 < n else mk.n, top, bot, "OTE"))
        while k1 < n and z[k1, 4] == leg:      # sisa leg yang sudah mati
            k1 += 1
        k = k1
    return out


def intersect(pois: list[tuple], otes: list[tuple]) -> list[tuple]:
    out = []
    for p in pois:
        for o in otes:
            if o[0] >= p[1] or p[0] >= o[1]:
                continue
            top, bot = min(p[2], o[2]), max(p[3], o[3])
            if top - bot < 0.2:
                continue
            out.append((max(p[0], o[0]), min(p[1], o[1]), top, bot, p[4] + "+OTE"))
    return sorted(set(out))


def run(mk: ps.Market, pois: dict) -> pd.DataFrame:
    keep = mk.pois
    mk.pois = pois
    try:
        t = pd.DataFrame(ps.run_side(mk, CFG, True) + ps.run_side(mk, CFG, False))
    finally:
        mk.pois = keep
    return t.sort_values("time").reset_index(drop=True) if not t.empty else t


def main() -> None:
    df = ps.load_m1("M5")
    mk = ps.Market(df, EMA_SPAN, BIAS_TF, MIN_SLOPE)
    print(f"Data M5 {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d} | cfg {CFG.name} slope {MIN_SLOPE}")
    base = mk.pois
    variants = {"base": base}
    for tf, name in ((15, "m15"), (60, "h1")):
        otes = {b: ote_zones(mk, b, tf) for b in (True, False)}
        print(f"Zona OTE {name}: buy {len(otes[True])} sell {len(otes[False])}")
        variants[f"add_{name}"] = {b: sorted(base[b] + otes[b]) for b in (True, False)}
        variants[f"only_{name}"] = otes
        variants[f"inside_{name}"] = {b: intersect(base[b], otes[b]) for b in (True, False)}
    rows, qrows = [], []
    for name, pois in variants.items():
        t = run(mk, pois)
        tr, te, al = ps.stats(t[t.time < ps.SPLIT]), ps.stats(t[t.time >= ps.SPLIT]), ps.stats(t)
        rows.append({"var": name, **{f"tr_{k}": v for k, v in tr.items() if k != "per_mgg"},
                     **{f"te_{k}": v for k, v in te.items() if k != "per_mgg"},
                     "all_PF": al["PF"], "all_R": al["R"], "all_DD": al["maxDD_R"]})
        q = t.groupby(t.time.dt.tz_convert(None).dt.to_period("Q"))["R"].sum().round(1)
        qrows.append(q.rename(name))
        if name.startswith("add"):
            print(f"\n{name} per jenis POI:\n" + t.groupby("poi")["R"].agg(["count", "sum", "mean"]).round(2).to_string())
    res = pd.DataFrame(rows)
    with pd.option_context("display.width", 250):
        print("\n" + res.to_string(index=False))
        print("\nR per kuartal:\n" + pd.concat(qrows, axis=1).T.to_string())
    res.to_csv(ps.settings.DATA_DIR / "pro_ote_check.csv", index=False)


if __name__ == "__main__":
    main()
