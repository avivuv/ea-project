"""
ORB (orb.py) di instrumen lain memakai cache M5 (pro_pairs). Hanya backtest.

    python -m tg_signal.orb_pairs

Bar M5 → konfirmasi = close tiap bar M5 (conf "bar"). Buffer SL = 0.6 × spread median, risiko minimum
= 6 × spread median (setara $0.1 / $1 di XAUUSD). Grid per instrumen: sesi (london/comex/ny) × OR 15/30 ×
SL opp/mid × TP 2/3/eod × bias none/with, entry market. Latih < Apr 2026 / uji ≥ Apr 2026.
"""
from __future__ import annotations

import itertools

import pandas as pd

from tg_signal import orb, settings
from tg_signal.pro_pairs import SYMBOLS, load
from tg_signal.session_sweep import Data

PASS = dict(pf=1.15, n_tr=50, n_te=35)


def main() -> None:
    rows = []
    syms = [s for s in SYMBOLS if s not in ("BTCUSD", "ETHUSD")] + ["BTCUSD", "ETHUSD"]
    for sym in dict.fromkeys(syms):
        df = load(sym, False)
        if df is None or len(df) < 50_000:
            print(f"{sym}: data tidak cukup")
            continue
        df = df[df.index >= "2025-06-16"]
        spr = float(df.spread.median())
        orb.SL_BUF, orb.RISK_MIN = 0.6 * spr, 6 * spr
        d = Data(df)
        opens = {s: orb.open_index(d, s) for s in orb.OPENS}
        for sess, L, sl, tp, bias in itertools.product(orb.OPENS, (15, 30), ("opp", "mid"), ("2", "3", "eod"),
                                                       ("none", "with")):
            cfg = orb.Cfg(sess, L, "bar", "market", sl, tp, bias, "none")
            t = orb.run(d, cfg, opens[sess])
            if t.empty:
                continue
            tr, te = orb.stats(t[t.time < orb.SPLIT]), orb.stats(t[t.time >= orb.SPLIT])
            rows.append({"sym": sym, "session": sess, "or": L, "sl": sl, "tp": tp, "bias": bias,
                         **{f"tr_{k}": v for k, v in tr.items()}, **{f"te_{k}": v for k, v in te.items()}})
        g = pd.DataFrame([r for r in rows if r["sym"] == sym])
        ok = g[(g.tr_PF > PASS["pf"]) & (g.te_PF > PASS["pf"]) & (g.tr_n >= PASS["n_tr"]) & (g.te_n >= PASS["n_te"])]
        print(f"{sym:<7} median PF latih {g.tr_PF.median():.2f} uji {g.te_PF.median():.2f} | lolos {len(ok)}/{len(g)}"
              + "".join(f" | {s}: {len(ok[ok.session == s])}" for s in orb.OPENS), flush=True)
    orb.SL_BUF, orb.RISK_MIN = 0.1, 1.0
    res = pd.DataFrame(rows)
    res.to_csv(settings.DATA_DIR / "orb_pairs.csv", index=False)
    cols = ["sym", "session", "or", "sl", "tp", "bias", "tr_n", "tr_avgR", "tr_PF", "tr_DD", "te_n", "te_avgR",
            "te_PF", "te_DD"]
    ok = res[(res.tr_PF > PASS["pf"]) & (res.te_PF > PASS["pf"]) & (res.tr_n >= PASS["n_tr"])
             & (res.te_n >= PASS["n_te"])]
    with pd.option_context("display.width", 250, "display.max_rows", 300):
        print("\nKonfigurasi live XAUUSD (ny OR15 SL opp TP2 bias with) di semua instrumen:")
        live = res[(res.session == "ny") & (res["or"] == 15) & (res.sl == "opp") & (res.tp == "2") & (res.bias == "with")]
        print(live[cols].to_string(index=False))
        print("\nMedian PF per instrumen × sesi (semua variasi):")
        print(res.groupby(["sym", "session"])[["tr_PF", "te_PF"]].median().unstack("session").round(2).to_string())
        print(f"\nLolos PF > {PASS['pf']} latih & uji: {len(ok)} dari {len(res)}")
        print(ok.sort_values(["sym", "te_PF"], ascending=[True, False])[cols].to_string(index=False))


if __name__ == "__main__":
    main()
