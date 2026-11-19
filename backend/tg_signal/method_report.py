"""
Backtest ulang semua metode yang sedang jalan (konfigurasi & exit = runner live), hasil per trade dalam R.

    python -m tg_signal.method_report          # → data/method_report_trades.csv + data/method_report.json

Metode (20 Nov 2026):
  Swing Donchian  XAU D1, XAU H4, BTC H4   — intraday.swing sinyal + exit swing_live.EXITS (swing_exit_study.simulate)
                  (JPY_H4_DON55 di ENTRY_OFF → tidak ikut)
  Trend MA Cross  XAU H4, XAU H1           — mac_exit_study.simulate cfg {"be": mac_live.BE_R}
  SMC Top-Down    XAUUSD                   — pro_check.run dengan pro_live.CFG / EMA_SPAN / BIAS_TF / MIN_SLOPE
  ORB NY          XAUUSD, ETHUSD           — orb.run dengan orb_live.SPECS
Sinyal Telegram tidak ikut (keputusan user 20 Nov 2026).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from tg_signal import settings

OUT_CSV = settings.DATA_DIR / "method_report_trades.csv"
OUT_JSON = settings.DATA_DIR / "method_report.json"


def swing_trades() -> list[pd.DataFrame]:
    from intraday import swing as sw
    from intraday import swing_exit_study as ses
    from intraday.swing_live import ENTRY_OFF, EXITS, METHODS
    out, cache = [], {}
    for mid, sym, vname, _ in METHODS:
        if mid in ENTRY_OFF:
            continue
        if sym not in cache:
            h1 = sw.load_h1(sym)
            cache[sym] = (h1, sw.d1_trend_series(h1), sw.MIN_SPREAD, sw.SLIP)
        h1, d1t, sw.MIN_SPREAD, sw.SLIP = cache[sym]
        v = {x.name: x for x in sw.variants()}[vname]
        b = sw.resample(h1, v.tf)
        aux = {"atr": ses.tf_on_h1(h1, b, sw.atr(b), v.tf), "close": ses.tf_on_h1(h1, b, b.close, v.tf)}
        t = ses.simulate(h1, sw.signals(h1, v, d1t), v, EXITS[mid], aux)
        out.append(pd.DataFrame({"time": t.time, "dir": t.dir, "R": t.r, "exit": t.why,
                                 "hold_h": t.hold_h}).assign(group="Swing Donchian", method=mid, symbol=sym,
                                                            split=str(sw.SPLIT.date())))
    return out


def mac_trades() -> list[pd.DataFrame]:
    from tg_signal import mac_exit_study as me
    from tg_signal.dndfx_backtest import resample
    from tg_signal.mac_deep import indicators, load_pair
    from tg_signal.mac_live import BE_R, METHODS
    h1 = load_pair("XAUUSD")
    out = []
    for mid, _, tf, _ in METHODS:
        df = h1 if tf == "1h" else resample(h1, tf)
        ind = indicators(df)
        t = me.simulate(df, ind, me.events(df, ind), {"be": BE_R})
        out.append(pd.DataFrame({"time": t.t_in, "dir": t.dir, "R": t.R, "exit": t.why, "hold_h": t.hrs})
                   .assign(group="Trend MA Cross", method=mid, symbol="XAUUSD", split=str(me.SPLIT.date())))
    return out


def smc_trades() -> list[pd.DataFrame]:
    from tg_signal import pro_strategy as ps
    from tg_signal.market_data import load_m1
    from tg_signal.pro_check import run
    from tg_signal.pro_live import BIAS_TF, CFG, EMA_SPAN, MIN_SLOPE
    t = run(ps.Market(load_m1("M5"), EMA_SPAN, BIAS_TF, MIN_SLOPE), CFG)
    d = np.where(t["dir"].astype(str).str.upper().isin(["BUY", "1", "TRUE"]), 1, -1)
    return [pd.DataFrame({"time": t.time, "dir": d, "R": t.R, "exit": t.get("outcome", ""), "hold_h": np.nan})
            .assign(group="SMC Top-Down", method="XAU_SMC", symbol="XAUUSD", split=str(ps.SPLIT.date()))]


def orb_trades() -> list[pd.DataFrame]:
    from tg_signal import orb
    from tg_signal.market_data import load_m1
    from tg_signal.orb_deep import setup
    from tg_signal.orb_live import SPECS
    from tg_signal.pro_pairs import load
    from tg_signal.session_sweep import Data
    out = []
    for sym, spec in SPECS.items():
        if sym == "XAUUSD":
            orb.SL_BUF, orb.RISK_MIN = spec.sl_buf, spec.risk_min
            m1 = load_m1("M1")
            d = Data(m1[m1.index >= "2025-06-16"])
        else:
            df = load(sym, False)
            d = setup(df[df.index >= "2025-06-16"])       # SL_BUF / RISK_MIN relatif spread (= orb_deep)
        t = orb.run(d, spec.cfg, orb.open_index(d, spec.cfg.session))
        out.append(pd.DataFrame({"time": t.time, "dir": np.where(t["dir"] == "BUY", 1, -1), "R": t.R,
                                 "exit": t.outcome, "hold_h": np.nan})
                   .assign(group="ORB NY", method=f"ORB_{sym}", symbol=sym, split=str(orb.SPLIT.date())))
    return out


def stats(r: np.ndarray) -> dict:
    if len(r) == 0:
        return {"n": 0}
    eq = np.cumsum(r)
    gl = -r[r < 0].sum()
    return {"n": int(len(r)), "wr": round(100 * float((r > 0).mean()), 1),
            "pf": round(float(r[r > 0].sum() / gl), 2) if gl > 0 else None,
            "avgR": round(float(r.mean()), 3), "totR": round(float(r.sum()), 1),
            "dd": round(float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()), 1)}


def build() -> dict:
    parts = []
    for name, fn in (("swing", swing_trades), ("mac", mac_trades), ("smc", smc_trades), ("orb", orb_trades)):
        print(f"… {name}", flush=True)
        parts += fn()
    tr = pd.concat(parts, ignore_index=True)
    tr["time"] = pd.to_datetime(tr["time"], utc=True)
    tr = tr.sort_values(["method", "time"]).reset_index(drop=True)
    tr.to_csv(OUT_CSV, index=False)
    methods = []
    for mid, g in tr.groupby("method", sort=False):
        r = g.R.to_numpy(float)
        split = pd.Timestamp(g.split.iloc[0], tz="UTC")
        la, uj = g[g.time < split].R.to_numpy(float), g[g.time >= split].R.to_numpy(float)
        eq = np.cumsum(r)
        yr = g.groupby(g.time.dt.year).R.agg(["sum", "size"])
        mo = g.groupby(g.time.dt.strftime("%Y-%m")).R.sum()
        span_days = max(1.0, (g.time.max() - g.time.min()).days)
        streak = mx = 0
        for x in r:
            streak = streak + 1 if x < 0 else 0
            mx = max(mx, streak)
        methods.append({
            "id": mid, "group": g.group.iloc[0], "symbol": g.symbol.iloc[0], "split": g.split.iloc[0],
            "start": g.time.min().strftime("%Y-%m-%d"), "end": g.time.max().strftime("%Y-%m-%d"),
            "all": stats(r), "train": stats(la), "test": stats(uj),
            "buy": stats(g[g.dir > 0].R.to_numpy(float)), "sell": stats(g[g.dir < 0].R.to_numpy(float)),
            "per_month_trades": round(len(r) / (span_days / 30.4), 1), "max_loss_streak": mx,
            "months_pos": int((mo > 0).sum()), "months": int(len(mo)),
            "equity": [[t.strftime("%Y-%m-%d %H:%M"), round(float(e), 2)] for t, e in zip(g.time, eq)],
            "yearly": [[int(y), round(float(s.sum_), 2), int(s.size_)] for y, s in
                       yr.rename(columns={"sum": "sum_", "size": "size_"}).iterrows()],
            "monthly": [[m, round(float(v), 2)] for m, v in mo.items()],
            "hist": np.histogram(np.clip(r, -1.5, 8), bins=np.arange(-1.5, 8.01, 0.5))[0].tolist(),
            "exits": {str(k): int(v) for k, v in g.exit.astype(str).value_counts().items()},
        })
        a = methods[-1]["all"]
        print(f"  {mid:14s} n {a['n']:4d} WR {a['wr']:5.1f} PF {a['pf']} avgR {a['avgR']:+.3f} "
              f"totR {a['totR']:+7.1f} DD {a['dd']:5.1f} | latih PF {methods[-1]['train'].get('pf')} "
              f"uji PF {methods[-1]['test'].get('pf')}", flush=True)
    rep = {"generated": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"), "methods": methods,
           "hist_edges": np.arange(-1.5, 8.01, 0.5).round(1).tolist()}
    OUT_JSON.write_text(json.dumps(rep), encoding="utf-8")
    return rep


if __name__ == "__main__":
    build()
