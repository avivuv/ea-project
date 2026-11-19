"""
Studi exit Trend MA Cross (entry sama dengan runner `mac_live`: cross langsung MA5 vs 13/21/34, filter slope EMA200,
SL 3 x ATR14, entry di close bar sinyal + spread). Yang divariasikan hanya cara keluar:

  base          exit saat bar close dengan MA5 di sisi berlawanan ketiga MA (aturan runner sekarang)
  tpX           TP tetap X R + exit cross MA tetap aktif
  tpX_only      TP tetap X R, tanpa exit cross (hanya TP / SL)
  beX           SL pindah ke entry setelah high mencapai +X R, lalu exit cross
  chK[_aX]      trailing chandelier: SL = high tertinggi sejak entry - K x ATR (ATR bar entry),
                aktif setelah +X R (default langsung); exit cross tetap aktif
  chK_nox       chandelier tanpa exit cross
  stepX         trailing per R: tiap high mencapai +nR, SL = +(n-1)R (mulai n = X)
  pX_Y          tutup 50% di +X R, sisanya exit cross (SL sisa pindah ke entry bila Y='be')

Intrabar konservatif: di tiap bar SL (stop yang berlaku dari bar sebelumnya) dicek lebih dulu, lalu TP,
lalu trailing di-update pakai high bar itu (berlaku mulai bar berikutnya).

    python -m tg_signal.mac_exit_study
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tg_signal.mac_deep import indicators, load_pair
from tg_signal.dndfx_backtest import resample

SPLIT = pd.Timestamp("2021-01-01", tz="UTC")
RECENT = pd.Timestamp("2024-01-01", tz="UTC")
SL_ATR = 3.0


def events(df: pd.DataFrame, ind: dict) -> list[tuple[int, int]]:
    ema, up = ind["ema"], ind["up"]
    ev = []
    for d in (1, -1):
        x = up[d]
        for k in np.nonzero(x[1:] & ~x[:-1])[0] + 1:
            if k > 210 and d * (ema[k] - ema[k - 10]) > 0:
                ev.append((int(k), d))
    return sorted(ev)


def simulate(df: pd.DataFrame, ind: dict, ev, cfg: dict) -> pd.DataFrame:
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    sp, at, n = df["spread"].to_numpy(float), ind["atr"], len(c)
    mir = {1: (o, h, l, c), -1: (-o, -l, -h, -c)}
    out, busy = [], -1
    for k, d in ev:
        if k <= busy or k + 1 >= n:
            continue
        O, H, L, C = mir[d]
        xs = ind["up"][-d]
        entry, dist = C[k], at[k] * SL_ATR
        if not dist > 0:
            continue
        stop, peak = entry - dist, entry
        tp = entry + cfg["tp"] * dist if cfg.get("tp") else None
        part = cfg.get("part")                      # (R, be?) -> 50% di R
        half_done, booked = False, 0.0
        px, j, why = C[-1], n - 1, "END"           # ruang cermin (bukan c[-1])
        for j in range(k + 1, n):
            if L[j] <= stop:                        # SL / trailing
                px, why = min(O[j], stop), "SL" if stop < entry else "TR"
                break
            if part and not half_done and H[j] >= entry + part[0] * dist:
                half_done, booked = True, 0.5 * part[0]
                if part[1]:
                    stop = max(stop, entry)
            if tp is not None and H[j] >= tp:
                px, why = max(O[j], tp), "TP"
                break
            if cfg.get("cross", True) and xs[j]:
                px, why = C[j], "X"
                break
            peak = max(peak, H[j])
            gain = (peak - entry) / dist
            if cfg.get("be") is not None and gain >= cfg["be"]:
                stop = max(stop, entry)
            if cfg.get("ch") is not None and gain >= cfg.get("ch_act", 0.0):
                stop = max(stop, peak - cfg["ch"] * at[k])
            if cfg.get("step") is not None and gain >= cfg["step"]:
                stop = max(stop, entry + (np.floor(gain) - 1) * dist)
        r = (px - entry) / dist
        r = booked + 0.5 * r if half_done else r
        out.append(dict(t_in=df.index[k], t_out=df.index[j], dir=d, R=r - sp[k] / dist, why=why,
                        hrs=(df.index[j] - df.index[k]).total_seconds() / 3600))
        busy = j
    return pd.DataFrame(out)


def pf(r: pd.Series) -> float:
    loss = -r[r <= 0].sum()
    return round(r[r > 0].sum() / loss, 2) if loss > 0 else np.nan


def summary(t: pd.DataFrame) -> dict:
    eq = t.R.cumsum()
    return dict(n=len(t), WR=round((t.R > 0).mean() * 100, 1), PF=pf(t.R),
                PF_train=pf(t.R[t.t_in < SPLIT]), PF_test=pf(t.R[t.t_in >= SPLIT]),
                PF_2024=pf(t.R[t.t_in >= RECENT]), PF_sell=pf(t.R[t.dir < 0]),
                avgR=round(t.R.mean(), 3), sumR=round(t.R.sum(), 1),
                maxDD=round((eq.cummax() - eq).max(), 1), avgWinR=round(t.R[t.R > 0].mean(), 2),
                hold_h=round(t.hrs.median(), 0))


VARIANTS: dict[str, dict] = {"base": {}}
for x in (1.0, 1.5, 2.0, 3.0, 4.0):
    VARIANTS[f"tp{x:g}"] = {"tp": x}
    VARIANTS[f"tp{x:g}_only"] = {"tp": x, "cross": False}
for x in (0.5, 1.0, 1.5):
    VARIANTS[f"be{x:g}"] = {"be": x}
for k in (1.5, 2.0, 3.0, 4.0):
    VARIANTS[f"ch{k:g}"] = {"ch": k}
    VARIANTS[f"ch{k:g}_a1"] = {"ch": k, "ch_act": 1.0}
    VARIANTS[f"ch{k:g}_nox"] = {"ch": k, "cross": False}
for x in (1.0, 2.0):
    VARIANTS[f"step{x:g}"] = {"step": x}
for x in (1.0, 1.5, 2.0):
    VARIANTS[f"p{x:g}_be"] = {"part": (x, True)}
    VARIANTS[f"p{x:g}"] = {"part": (x, False)}


def main() -> None:
    pd.set_option("display.width", 220)
    h1 = load_pair("XAUUSD")
    for tf in ("1h", "4h"):
        df = h1 if tf == "1h" else resample(h1, tf)
        ind = indicators(df)
        ev = events(df, ind)
        rows = [dict(var=name, **summary(simulate(df, ind, ev, cfg))) for name, cfg in VARIANTS.items()]
        res = pd.DataFrame(rows).set_index("var")
        base = res.loc["base"]
        res["dPF_test"] = (res.PF_test - base.PF_test).round(2)
        print(f"\n== XAUUSD {tf}: {df.index[0]:%Y-%m-%d} s/d {df.index[-1]:%Y-%m-%d} (train < {SPLIT:%Y}, test >=)")
        print(res.sort_values("PF_test", ascending=False).to_string())
        res.to_csv(f"{__file__.rsplit('tg_signal', 1)[0]}tg_signal/data/mac_exit_{tf}.csv")


if __name__ == "__main__":
    main()
