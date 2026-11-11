"""
Studi pola: sinyal seperti apa yang berhasil TP (entry market langsung, SL 30 dari entry)?

    python -m tg_signal.pattern_study                       # latih Agu–Sep, uji Okt–Nov 2026 (M1)
    python -m tg_signal.pattern_study --split 2026-09-15    # ubah titik pisah

Prinsip:
- Semua fitur hanya memakai informasi yang ADA saat pesan diterima (tanpa melihat masa depan).
- Pola/model dicari HANYA di data latih. Data uji dipakai sekali untuk menilai.
- Hasil (TP/SL) dihitung dengan mesin backtest_tg (spread asli per bar M1).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal import backtest_tg as bt
from tg_signal.price_resolver import resolve_zone
from tg_signal.store import Store

TPS = (10, 15, 20, 30)
TARGET_TP = 20                      # target model: apakah TP20 tercapai sebelum SL30
KEEP_FRACTIONS = (0.3, 0.5, 0.7)


# ── Indikator ───────────────────────────────────────────────────────────────
def _ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def _rsi(x: pd.Series, n: int = 14) -> pd.Series:
    d = x.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tr = pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift()).abs(),
                    (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _tf(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


class Indicators:
    """Indikator M1/M5/H1; nilai TF besar diambil dari bar yang SUDAH close (shift 1)."""

    def __init__(self, m1: pd.DataFrame):
        self.m1 = m1
        c = m1["close"]
        self.t = m1.index
        self.c = c.to_numpy()
        self.o = m1["open"].to_numpy()
        self.h = m1["high"].to_numpy()
        self.l = m1["low"].to_numpy()
        self.rsi1 = _rsi(c).to_numpy()
        self.atr1 = _atr(m1).to_numpy()
        m5, h1 = _tf(m1, "5min"), _tf(m1, "1h")
        idx5, idx1h = m1.index.floor("5min"), m1.index.floor("1h")

        def lag(s: pd.Series, idx) -> np.ndarray:      # nilai bar TF sebelumnya yang sudah close
            return s.shift(1).reindex(idx).to_numpy()

        self.ema20_5 = lag(_ema(m5["close"], 20), idx5)
        self.ema50_5 = lag(_ema(m5["close"], 50), idx5)
        self.rsi5 = lag(_rsi(m5["close"]), idx5)
        self.atr5 = lag(_atr(m5), idx5)
        self.ema20_h1 = lag(_ema(h1["close"], 20), idx1h)
        self.ema50_h1 = lag(_ema(h1["close"], 50), idx1h)
        day = (m1.index + timedelta(hours=7)).normalize()
        self.day_open = m1["open"].groupby(day).transform("first").to_numpy()
        self.day_high = m1["high"].groupby(day).cummax().to_numpy()
        self.day_low = m1["low"].groupby(day).cummin().to_numpy()


def features(sig: bt.Signal, bars: bt.Bars, ind: Indicators) -> dict | None:
    s = bars.first_bar_after(sig.time)
    k = s - 2                                   # bar M1 terakhir yang pasti sudah close
    if k < 300 or s >= bars.n:
        return None
    g = 1 if sig.direction == "BUY" else -1
    ref = bars.o[s - 1]
    z = resolve_zone(sig.direction, sig.level_first, sig.level_last, ref=ref)
    c, h, l = ind.c, ind.h, ind.l
    hi60, lo60 = h[k - 59:k + 1].max(), l[k - 59:k + 1].min()
    rng60 = max(hi60 - lo60, 1e-9)
    pos60 = (ref - lo60) / rng60 if g == 1 else (hi60 - ref) / rng60   # 0 = di ujung "murah" utk arah sinyal
    atr5 = ind.atr5[k] if not np.isnan(ind.atr5[k]) else ind.atr1[k] * 2.2
    dhi, dlo = ind.day_high[k], ind.day_low[k]
    drng = max(dhi - dlo, 1e-9)
    return {
        "is_buy": int(g == 1),
        "hour_wib": (sig.time.hour + 7) % 24,
        "weekday": (sig.time + timedelta(hours=7)).weekday(),
        "dist_to_zero": g * (ref - z.zero),                 # >0: harga belum masuk zona
        "zone_width": z.width,
        "ret_1m": g * (c[k] - c[k - 1]),
        "ret_5m": g * (c[k] - c[k - 5]),
        "ret_15m": g * (c[k] - c[k - 15]),
        "ret_60m": g * (c[k] - c[k - 60]),
        "atr_m1": ind.atr1[k],
        "atr_m5": atr5,
        "pos_range60": pos60,
        "pos_day": (ref - dlo) / drng if g == 1 else (dhi - ref) / drng,
        "from_day_open": g * (ref - ind.day_open[k]),
        "ema_m5_align": float(np.sign(g * (ind.ema20_5[k] - ind.ema50_5[k]))) if not np.isnan(ind.ema50_5[k]) else 0.0,
        "dist_ema20_m5_atr": g * (ref - ind.ema20_5[k]) / atr5 if not np.isnan(ind.ema20_5[k]) else 0.0,
        "ema_h1_align": float(np.sign(g * (ind.ema20_h1[k] - ind.ema50_h1[k]))) if not np.isnan(ind.ema50_h1[k]) else 0.0,
        "rsi_m1": ind.rsi1[k] if g == 1 else 100 - ind.rsi1[k],
        "rsi_m5": (ind.rsi5[k] if g == 1 else 100 - ind.rsi5[k]) if not np.isnan(ind.rsi5[k]) else 50.0,
        "last_candle": float(np.sign(g * (c[k] - ind.o[k]))),
    }


# ── Dataset ─────────────────────────────────────────────────────────────────
def build_dataset(store: Store, bars: bt.Bars, ind: Indicators, sigs: list[bt.Signal]) -> pd.DataFrame:
    meta = {r["msg_id"]: r for r in store.conn.execute(
        "SELECT msg_id, sender_name FROM messages").fetchall()}
    alerts = [datetime.fromisoformat(r[0]) for r in store.conn.execute(
        "SELECT date_utc FROM messages WHERE kind='OTHER' AND upper(text) LIKE '%NOW%' AND length(text) < 30")]
    alerts = np.array(sorted(a.timestamp() for a in alerts))

    rows = []
    prev_results: list[tuple[datetime, datetime | None, str, str]] = []   # (time, exit_time, dir, outcome)
    day_count: dict = {}
    for i, sg in enumerate(sigs):
        f = features(sg, bars, ind)
        if f is None:
            continue
        res = {tp: bt.simulate(sg, bt.Variant("MARKET", 1, tp, "entry"), bars) for tp in TPS}
        if any(r["outcome"] not in ("TP", "SL") for r in res.values()):
            continue
        # konteks sinyal sebelumnya (hanya yang hasilnya SUDAH diketahui saat sinyal ini masuk)
        known = [p for p in prev_results if p[1] is not None and p[1] <= sg.time]
        last_known = known[-1][3] if known else ""
        prev = sigs[i - 1] if i else None
        d = (sg.time + timedelta(hours=7)).date()
        day_count[d] = day_count.get(d, 0) + 1
        ts = sg.time.timestamp()
        pos = np.searchsorted(alerts, ts)
        alert_gap = ts - alerts[pos - 1] if pos else 1e9
        f.update({
            "admin": meta.get(sg.msg_id, {"sender_name": ""})["sender_name"] or "",
            "mins_since_prev": (sg.time - prev.time).total_seconds() / 60 if prev else 999.0,
            "same_dir_as_prev": int(prev is not None and prev.direction == sg.direction),
            "nth_signal_today": day_count[d],
            "prev_known_tp": 1 if last_known == "TP" else (-1 if last_known == "SL" else 0),
            "had_now_alert": int(alert_gap < 180),
        })
        ex = res[TARGET_TP].get("exit_time")
        prev_results.append((sg.time, ex.to_pydatetime() if ex is not None else None, sg.direction,
                             res[TARGET_TP]["outcome"]))
        for tp, r in res.items():
            f[f"pips_tp{tp}"] = r["pips"]
        f["time"] = sg.time
        f["y_tp"] = int(res[TARGET_TP]["outcome"] == "TP")
        rows.append(f)
    df = pd.DataFrame(rows)
    df["admin"] = df["admin"].astype("category")
    return df


FEATURES = ["is_buy", "hour_wib", "weekday", "dist_to_zero", "zone_width", "ret_1m", "ret_5m", "ret_15m",
            "ret_60m", "atr_m1", "atr_m5", "pos_range60", "pos_day", "from_day_open", "ema_m5_align",
            "dist_ema20_m5_atr", "ema_h1_align", "rsi_m1", "rsi_m5", "last_candle", "mins_since_prev",
            "same_dir_as_prev", "nth_signal_today", "prev_known_tp", "had_now_alert"]


# ── Evaluasi ────────────────────────────────────────────────────────────────
def ev_table(df: pd.DataFrame) -> str:
    out = []
    for tp in TPS:
        p = df[f"pips_tp{tp}"]
        out.append(f"TP{tp}: n={len(p)} WR={100 * (p > 0).mean():.1f}% avg={p.mean():+.2f} total={p.sum():+.0f}")
    return " | ".join(out)


def univariate(train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    """Korelasi Spearman fitur vs hasil pips TP20, di latih dan uji. Pola nyata = tanda sama & tidak nol."""
    rows = []
    for f in FEATURES:
        a = train[f].corr(train[f"pips_tp{TARGET_TP}"], method="spearman")
        b = test[f].corr(test[f"pips_tp{TARGET_TP}"], method="spearman")
        rows.append({"fitur": f, "corr_latih": round(a, 3), "corr_uji": round(b, 3),
                     "konsisten": "ya" if np.sign(a) == np.sign(b) and min(abs(a), abs(b)) >= 0.03 else ""})
    return pd.DataFrame(rows).sort_values("corr_latih", key=abs, ascending=False)


def model_study(train: pd.DataFrame, test: pd.DataFrame) -> list[str]:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X_tr, y_tr = train[FEATURES].to_numpy(float), train["y_tp"].to_numpy()
    X_te, y_te = test[FEATURES].to_numpy(float), test["y_tp"].to_numpy()
    models = {
        "logistic": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000)),
        "gboost": lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150,
                                                         min_samples_leaf=40, l2_regularization=1.0),
    }
    lines = []
    for name, mk in models.items():
        # pilih fraksi yang dipertahankan HANYA dari validasi silang waktu di data latih
        cv_ev = {q: [] for q in KEEP_FRACTIONS}
        cv_auc = []
        for tr_i, va_i in TimeSeriesSplit(n_splits=4).split(X_tr):
            m = mk().fit(X_tr[tr_i], y_tr[tr_i])
            p = m.predict_proba(X_tr[va_i])[:, 1]
            if len(set(y_tr[va_i])) > 1:
                cv_auc.append(roc_auc_score(y_tr[va_i], p))
            pips = train[f"pips_tp{TARGET_TP}"].to_numpy()[va_i]
            for q in KEEP_FRACTIONS:
                keep = p >= np.quantile(p, 1 - q)
                cv_ev[q].append(pips[keep].mean())
        best_q = max(KEEP_FRACTIONS, key=lambda q: np.mean(cv_ev[q]))
        m = mk().fit(X_tr, y_tr)
        p_tr = m.predict_proba(X_tr)[:, 1]
        thr = np.quantile(p_tr, 1 - best_q)           # ambang dari data latih
        p_te = m.predict_proba(X_te)[:, 1]
        kept = test[p_te >= thr]
        lines.append(f"[{name}] AUC CV latih={np.mean(cv_auc):.3f} | AUC uji={roc_auc_score(y_te, p_te):.3f} | "
                     f"EV CV per fraksi: " + ", ".join(f"{q:.0%}={np.mean(v):+.2f}" for q, v in cv_ev.items())
                     + f" → pilih {best_q:.0%}")
        lines.append(f"    UJI semua sinyal : {ev_table(test)}")
        lines.append(f"    UJI lolos filter : {ev_table(kept)}")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Studi pola sinyal TP vs SL")
    ap.add_argument("--split", default="2026-10-01", help="awal periode uji (YYYY-MM-DD)")
    args = ap.parse_args()
    split = datetime.fromisoformat(args.split).replace(tzinfo=timezone.utc)

    m1 = bt.load_m1("M1")
    bars = bt.Bars(m1)
    ind = Indicators(m1)
    store = Store(settings.DB_PATH)
    sigs = bt.load_signals(store, m1.index[0].to_pydatetime(), m1.index[-1].to_pydatetime())
    df = build_dataset(store, bars, ind, sigs)
    df.to_csv(settings.DATA_DIR / "pattern_dataset.csv", index=False)
    train, test = df[df["time"] < split], df[df["time"] >= split]
    print(f"Dataset: {len(df)} sinyal | latih {len(train)} (s/d {args.split}) | uji {len(test)}")
    print(f"Basis LATIH: {ev_table(train)}")
    print(f"Basis UJI  : {ev_table(test)}\n")

    print("== Fitur satu per satu (korelasi dengan pips TP20; 'ya' = arah sama di latih & uji) ==")
    with pd.option_context("display.width", 200):
        print(univariate(train, test).to_string(index=False))

    print("\n== Per admin (pips TP20) ==")
    print(df.groupby(["admin", df["time"] >= split], observed=True)[f"pips_tp{TARGET_TP}"]
          .agg(["size", "mean"]).round(2).to_string())

    print("\n== Model (ambang & fraksi dipilih di data latih saja) ==")
    for line in model_study(train, test):
        print(line)


if __name__ == "__main__":
    main()
