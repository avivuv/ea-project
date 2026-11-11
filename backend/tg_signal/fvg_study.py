"""
Uji aturan: "entry hanya bila saat sinyal masuk sudah ada FVG searah di zona".

    python -m tg_signal.fvg_study

Memakai dataset dari pattern_study (pips per TP sudah dihitung, entry market langsung, SL 30 dari entry).
Latih = sebelum 1 Okt 2026, uji = sesudahnya. Aturan dinilai di KEDUA periode — pola nyata harus
membaik di dua-duanya.
"""
from __future__ import annotations

import pandas as pd

from tg_signal import settings
from tg_signal import backtest_tg as bt
from tg_signal.fvg_context import FVGIndex
from tg_signal.price_resolver import resolve_zone
from tg_signal.store import Store

TPS = (10, 15, 20, 30)
SPLIT = pd.Timestamp("2026-10-01", tz="UTC")


def summarize(g: pd.DataFrame) -> dict:
    out = {"n": len(g)}
    for tp in TPS:
        p = g[f"pips_tp{tp}"]
        out[f"WR{tp}"] = round(100 * (p > 0).mean(), 1) if len(p) else None
        out[f"avg{tp}"] = round(p.mean(), 2) if len(p) else None
    return out


def main() -> None:
    ds = pd.read_csv(settings.DATA_DIR / "pattern_dataset.csv", parse_dates=["time"])
    m1 = bt.load_m1("M1")
    bars = bt.Bars(m1)
    idx = {tf: FVGIndex(m1, tf) for tf in ("M1", "M5", "M15")}
    lookback = {"M1": 60, "M5": 24, "M15": 16}           # ~1 jam / 2 jam / 4 jam
    store = Store(settings.DB_PATH)
    lv = pd.read_sql("SELECT received_utc, direction, level_first, level_last FROM signals", store.conn)
    lv["time"] = pd.to_datetime(lv["received_utc"])
    ds = ds.merge(lv[["time", "level_first", "level_last"]], on="time", how="left")

    rows = []
    for r in ds.itertuples():
        s = bars.first_bar_after(r.time.to_pydatetime())
        ref = bars.o[s - 1]
        d = "BUY" if r.is_buy else "SELL"
        z = resolve_zone(d, int(r.level_first), int(r.level_last), ref=ref)
        ctx = {}
        for tf, ix in idx.items():
            ctx.update(ix.context(r.time, d, z.bottom, z.top, ref, tp_dist=2.0, lookback_bars=lookback[tf]))
        rows.append(ctx)
    df = pd.concat([ds.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    df.to_csv(settings.DATA_DIR / "fvg_dataset.csv", index=False)

    rules = {
        "SEMUA sinyal (entry langsung)": df.index == df.index,
        "M5 FVG searah di zona (open/retest)": df["m5_same_valid"] > 0,
        "M5 FVG searah di zona, masih OPEN": df["m5_same_open"] > 0,
        "M5 FVG searah di zona, sudah RETEST": df["m5_same_touched"] > 0,
        "TANPA M5 FVG searah di zona": df["m5_same_valid"] == 0,
        "M1 FVG searah di zona": df["m1_same_valid"] > 0,
        "M15 FVG searah di zona": df["m15_same_valid"] > 0,
        "M5 FVG searah + tanpa penghalang M1": (df["m5_same_valid"] > 0) & (df["m1_blocker"] == 0),
        "M5 FVG searah + tanpa penghalang M5": (df["m5_same_valid"] > 0) & (df["m5_blocker"] == 0),
        "Ada penghalang M1 di jalur TP": df["m1_blocker"] > 0,
        "Tanpa penghalang M1 di jalur TP": df["m1_blocker"] == 0,
    }
    out = []
    for name, mask in rules.items():
        for per, sub in (("latih Agu-Sep", df[mask & (df["time"] < SPLIT)]),
                         ("uji Okt-Nov", df[mask & (df["time"] >= SPLIT)])):
            out.append({"aturan": name, "periode": per, **summarize(sub)})
    res = pd.DataFrame(out)
    with pd.option_context("display.width", 250, "display.max_rows", 100):
        print(res.to_string(index=False))
    res.to_csv(settings.DATA_DIR / "fvg_study_result.csv", index=False)


if __name__ == "__main__":
    main()
