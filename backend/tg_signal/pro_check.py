"""
Uji ketahanan kandidat terkuat pro_strategy (ema_nopd_nosw_fvg_RR3_all).

    python -m tg_signal.pro_check

1. Rincian: per bulan, per arah, per jam masuk (UTC), per jenis POI.
2. Variasi tetangga (satu parameter diubah tiap kali): RR, EMA, umur POI, tunggu konfirmasi,
   buffer SL, masa pending. Kandidat yang nyata harus tetap positif di sekitarnya.
3. Validasi M1: trade hasil simulasi M5 yang periodenya punya data M1 diulang di bar M1
   (fill limit & SL/TP diperiksa per menit) → bandingkan hasilnya.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tg_signal import pro_strategy as ps
from tg_signal import settings
from tg_signal.market_data import load_m1

BASE = ps.Cfg("ema", False, False, "fvg", 3.0, False, False)


def run(mk: ps.Market, cfg: ps.Cfg) -> pd.DataFrame:
    t = pd.DataFrame(ps.run_side(mk, cfg, True) + ps.run_side(mk, cfg, False))
    return t.sort_values("time").reset_index(drop=True)


def line(t: pd.DataFrame) -> str:
    tr, te = ps.stats(t[t.time < ps.SPLIT]), ps.stats(t[t.time >= ps.SPLIT])
    return (f"latih {tr['trades']:4d} tr PF {tr['PF']:.2f} R {tr['R']:+6.1f} DD {tr['maxDD_R']:5.1f} | "
            f"uji {te['trades']:4d} tr PF {te['PF']:.2f} R {te['R']:+6.1f} DD {te['maxDD_R']:5.1f}")


def breakdown(t: pd.DataFrame) -> None:
    t = t.copy()
    t["bulan"] = t.time.dt.strftime("%Y-%m")
    g = t.groupby("bulan").agg(trade=("R", "size"), wr=("R", lambda r: round(100 * (r > 0).mean())),
                               R=("R", "sum"))
    g["R_kumulatif"] = g.R.cumsum()
    print("\nPer bulan:\n" + g.round(1).to_string())
    print(f"Bulan positif: {(g.R > 0).sum()} dari {len(g)}")
    for col, name in (("dir", "arah"), ("poi", "jenis POI")):
        print(f"\nPer {name}:\n" + t.groupby(col).R.agg(["size", "sum", "mean"]).round(2).to_string())
    t["jam"] = t.time.dt.hour
    t["sesi"] = pd.cut(t.jam, [-1, 6, 11, 16, 23], labels=["Asia 00-07", "London 07-12", "NY 12-17", "Sore 17-24"])
    print("\nPer sesi (UTC):\n" + t.groupby("sesi", observed=True).R.agg(["size", "sum", "mean"]).round(2).to_string())
    print("\nPer jarak SL (pips):\n" + t.groupby(pd.cut(t.risk_pips, [0, 20, 35, 50, 75, 100]), observed=True)
          .R.agg(["size", "sum", "mean"]).round(2).to_string())


def neighbours(df: pd.DataFrame, mk: ps.Market) -> None:
    print("\nVariasi tetangga:")
    print(f"  {'DASAR':<22} {line(run(mk, BASE))}")
    for rr in (2.0, 2.5, 4.0):
        print(f"  {'RR ' + str(rr):<22} {line(run(mk, ps.Cfg(**{**BASE.__dict__, 'rr': rr})))}")
    for span in (34, 100):
        print(f"  {'EMA ' + str(span):<22} {line(run(ps.Market(df, span), BASE))}")
    for attr, vals in (("POI_AGE", (288, 5 * 288)), ("ARM_WAIT", (24, 48)), ("SL_BUF", (0.2, 0.5)),
                       ("PEND_WAIT", (6, 24)), ("POI_MIN", (0.3, 1.0))):
        orig = getattr(ps, attr)
        for v in vals:
            setattr(ps, attr, v)
            m = ps.Market(df) if attr == "POI_MIN" else mk
            print(f"  {attr + ' ' + str(v):<22} {line(run(m, BASE))}")
        setattr(ps, attr, orig)


def m1_validate(t: pd.DataFrame) -> None:
    m1 = load_m1("M1")
    t = t[(t.time >= m1.index[0] + pd.Timedelta(hours=1)) & (t.exit_time <= m1.index[-1])].copy()
    tt = m1.index.values.astype("datetime64[ns]")
    lo, hi, sp = m1["low"].to_numpy(), m1["high"].to_numpy(), m1["spread"].to_numpy()
    out = []
    for r in t.itertuples():
        buy = r.dir == "BUY"
        g = 1 if buy else -1
        i = int(np.searchsorted(tt, np.datetime64(r.time.tz_convert(None)), side="left"))
        end = min(len(tt), i + 2 * 1440)
        risk = abs(r.entry - r.sl)
        res, filled = np.nan, False
        for j in range(i, end):
            bl, bh = (lo[j], hi[j]) if buy else (-hi[j], -lo[j])
            ent, sl, tp = g * r.entry, g * r.sl, g * r.tp
            cost, xadj = (sp[j], 0.0) if buy else (0.0, sp[j])
            if not filled:
                if bl + cost <= ent + 1e-9:
                    filled = True
                    if bl - xadj <= sl:
                        res = -1.0
                        break
                continue
            if bl - xadj <= sl:
                res = -1.0
                break
            if bh - xadj >= tp:
                res = (tp - ent) / risk
                break
        out.append(res)
    t["R_m1"] = out
    ok = t.dropna(subset=["R_m1"])
    same = (np.sign(ok.R) == np.sign(ok.R_m1)).mean() * 100
    print(f"\nValidasi M1 ({ok.time.min():%Y-%m-%d} → {ok.time.max():%Y-%m-%d}): {len(ok)} trade, "
          f"hasil sama {same:.0f}%")
    print(f"  R di M5: {ok.R.sum():+.1f}  |  R di M1: {ok.R_m1.sum():+.1f}  "
          f"(tidak terisi/terbuka di M1: {t.R_m1.isna().sum()})")


def main() -> None:
    df = load_m1("M5")
    mk = ps.Market(df)
    t = run(mk, BASE)
    print(f"Kandidat {BASE.name}: {line(t)}")
    breakdown(t)
    m1_validate(t)
    neighbours(df, mk)
    t.to_csv(settings.DATA_DIR / "pro_candidate_trades.csv", index=False)


if __name__ == "__main__":
    main()
