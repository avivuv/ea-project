"""
Backtest sinyal Telegram di atas data M1 (Tahap 2).

    python -m tg_signal.backtest_tg                 # semua variasi, ringkasan
    python -m tg_signal.backtest_tg --validate      # cocokkan simulasi vs label laporan provider
    python -m tg_signal.backtest_tg --check-offset  # cek offset jam server MT5 vs Telegram

Asumsi (konservatif):
- Harga bar = BID. BUY masuk di ASK (bid + spread), keluar di BID. SELL kebalikannya.
- Sinyal diproses mulai bar M1 pertama yang buka SETELAH pesan diterima.
- Harga referensi resolve 2 digit = open bar M1 tempat pesan diterima.
- Limit order: di bar fill hanya SL yang dicek (TP baru dihitung bar berikutnya).
- SL & TP tersentuh di bar yang sama → dihitung SL.
- Konfirmasi: dievaluasi saat bar TF (M1/M5) close; entry market di open bar M1 berikutnya.
- Masa berlaku (D8): setelah zona disentuh, sinyal hangus bila harga mencapai zero ± TG_EXPIRE_TP_PIPS
  ke arah TP, atau melewati last sejauh SL, sebelum kita entry. Tanpa timeout.
- Setiap sinyal disimulasikan independen (belum ada batas posisi bersamaan).
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from tg_signal import settings
from tg_signal.confirmation import confirmed
from tg_signal.market_data import load_m1
from tg_signal.price_resolver import resolve_zone
from tg_signal.store import Store

PIP = settings.PIP_SIZE
HORIZON_BARS = 2 * 1440          # batas simulasi per sinyal (2 hari bar M1)
DEDUP_SEC = settings.TG_DUPLICATE_WINDOW_SEC


# ── Data ────────────────────────────────────────────────────────────────────
@dataclass
class Signal:
    time: datetime
    direction: str
    level_first: int
    level_last: int
    sl_pips: float
    msg_id: int


def load_signals(store: Store, start: datetime, end: datetime) -> list[Signal]:
    rows = store.conn.execute(
        """SELECT s.received_utc, s.direction, s.level_first, s.level_last, s.sl_pips, m.msg_id
           FROM signals s JOIN messages m ON m.id = s.message_id
           WHERE s.received_utc >= ? AND s.received_utc < ? ORDER BY s.received_utc""",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    out: list[Signal] = []
    last_seen: dict[tuple, datetime] = {}
    for r in rows:
        t = datetime.fromisoformat(r["received_utc"])
        key = (r["direction"], r["level_first"], r["level_last"])
        prev = last_seen.get(key)
        last_seen[key] = t
        if prev and (t - prev).total_seconds() <= DEDUP_SEC:
            continue                                  # pesan pendek + pesan lengkap = 1 sinyal
        out.append(Signal(t, r["direction"], r["level_first"], r["level_last"], r["sl_pips"], r["msg_id"]))
    return out


class Bars:
    """Array M1 + pemetaan penutupan bar M5."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.t = df.index.values.astype("datetime64[ns]")
        self.o = df["open"].to_numpy(float)
        self.h = df["high"].to_numpy(float)
        self.l = df["low"].to_numpy(float)
        self.c = df["close"].to_numpy(float)
        self.spr = df["spread"].to_numpy(float)
        self.n = len(df)
        m5 = df.resample("5min", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        self.m5 = {k: m5[k].to_numpy(float) for k in ("open", "high", "low", "close")}
        m5_pos = {ts: i for i, ts in enumerate(m5.index)}
        bucket = df.index.floor("5min")
        nxt_bucket = (df.index + pd.Timedelta(minutes=1)).floor("5min")
        # bar M1 ke-i menutup bar M5 bila bar M1 berikutnya masuk bucket baru
        self.m5_close = np.full(self.n, -1, dtype=np.int64)
        closes = (bucket != nxt_bucket)
        # juga tutup bucket bila ada gap data (bar berikut tidak ada / beda bucket)
        nxt_index_bucket = np.append(bucket[1:].values, np.datetime64("NaT"))
        closes = closes | (bucket.values != nxt_index_bucket)
        for i in np.nonzero(closes)[0]:
            self.m5_close[i] = m5_pos.get(bucket[i], -1)

    def first_bar_after(self, ts: datetime) -> int:
        return int(np.searchsorted(self.t, np.datetime64(ts.replace(tzinfo=None), "ns"), side="right"))


# ── Simulasi ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Variant:
    entry: str          # ZERO | MID | LAST (limit) | LAYER (3 limit) | FVG | OB | OBIM (konfirmasi)
    tf: int             # 1 | 5 (hanya untuk konfirmasi)
    tp_pips: float
    sl_from: str = "entry"   # entry: SL = entry − SL pips | zone: SL = LAST − SL pips

    @property
    def name(self) -> str:
        sl = "SLentry" if self.sl_from == "entry" else "SLzone"
        if self.entry in ("ZERO", "MID", "LAST"):
            return f"LIMIT_{self.entry}_TP{self.tp_pips:g}_{sl}"
        if self.entry == "LAYER":
            return f"LAYER3_TP{self.tp_pips:g}_SLzone"
        return f"{self.entry}_M{self.tf}_TP{self.tp_pips:g}_{sl}"


def _space(bars: Bars, direction: str, lo: int, hi: int):
    """Ubah harga ke 'ruang BUY': SELL dinegasikan supaya satu logika untuk dua arah."""
    sl = slice(lo, hi)
    if direction == "BUY":
        return bars.o[sl], bars.h[sl], bars.l[sl], bars.c[sl], bars.spr[sl], True
    return -bars.o[sl], -bars.l[sl], -bars.h[sl], -bars.c[sl], bars.spr[sl], False


def simulate(sig: Signal, v: Variant, bars: Bars) -> dict:
    res = {"time": sig.time, "msg_id": sig.msg_id, "direction": sig.direction,
           "variant": v.name, "outcome": "", "pips": 0.0, "entry_time": None, "zero": None, "last": None}
    s = bars.first_bar_after(sig.time)
    if s <= 0 or s >= bars.n:
        res["outcome"] = "NO_DATA"
        return res
    gap = (np.datetime64(sig.time.replace(tzinfo=None), "ns") - bars.t[s - 1]) / np.timedelta64(1, "m")
    if gap > 5:
        res["outcome"] = "NO_DATA"
        return res

    zone = resolve_zone(sig.direction, sig.level_first, sig.level_last, ref=bars.o[s - 1],
                        width_min=settings.TG_ZONE_WIDTH_MIN, width_max=settings.TG_ZONE_WIDTH_MAX)
    res["zero"], res["last"] = zone.zero, zone.last
    if zone.distance > settings.TG_MAX_ZONE_DISTANCE:
        res["outcome"] = "REJECTED_DISTANCE"
        return res

    end = min(bars.n, s + HORIZON_BARS)
    o, h, l, c, spr, is_buy = _space(bars, sig.direction, s, end)
    sgn = 1 if is_buy else -1
    zero, last = sgn * zone.zero, sgn * zone.last
    mid = (zero + last) / 2
    sl_dist = sig.sl_pips * PIP
    tp_dist = v.tp_pips * PIP
    exp_tp = zero + settings.TG_EXPIRE_TP_PIPS * PIP
    exp_sl = last - sl_dist
    limit_level = {"ZERO": zero, "MID": mid, "LAST": last}.get(v.entry)

    # Array konfirmasi (ruang BUY, indeks global) untuk TF yang dipakai
    if limit_level is None:
        co, ch, cl, cc = _full_space(bars, is_buy, v.tf)

    if v.entry == "LAYER":
        return _simulate_layer(res, bars, s, o, h, l, c, spr, is_buy, zero, mid, last, sl_dist, tp_dist)

    touched = False
    entry_i = None
    entry_px = sl_px = tp_px = 0.0
    for j in range(len(o)):
        fill_cost = spr[j] if is_buy else 0.0           # BUY bayar spread saat masuk
        exit_adj = 0.0 if is_buy else spr[j]            # SELL bayar spread saat keluar

        if entry_i is None:
            if not touched and l[j] + fill_cost <= zero:
                touched = True
            if not touched:
                continue
            if limit_level is not None:
                if l[j] + fill_cost <= limit_level:
                    entry_i = j
                    entry_px = min(limit_level, o[j] + fill_cost)   # gap melewati limit → fill di open
                    sl_px = (entry_px if v.sl_from == "entry" else last) - sl_dist
                    tp_px = entry_px + tp_dist
                    if l[j] - exit_adj <= sl_px:                     # di bar fill: hanya cek SL
                        return _close(res, bars, s, j, j, (sl_px - entry_px) / PIP, "SL")
                    continue
            # hangus (D8) sebelum entry
            if h[j] >= exp_tp:
                res["outcome"] = "EXPIRED_TP"
                return res
            if l[j] <= exp_sl:
                res["outcome"] = "EXPIRED_SL"
                return res
            if limit_level is None:
                k = s + j if v.tf == 1 else int(bars.m5_close[s + j])
                ok = k >= 0 and confirmed(v.entry, "BUY", co, ch, cl, cc, k, zero)
                if ok and j + 1 < len(o):
                    entry_i = j + 1
                    entry_px = o[j + 1] + (spr[j + 1] if is_buy else 0.0)
                    sl_px = (entry_px if v.sl_from == "entry" else min(last, entry_px)) - sl_dist
                    tp_px = entry_px + tp_dist
            continue

        # posisi terbuka
        if j == entry_i and limit_level is not None:
            continue
        if l[j] - exit_adj <= sl_px:
            return _close(res, bars, s, entry_i, j, (sl_px - entry_px) / PIP, "SL")
        if h[j] - exit_adj >= tp_px:
            return _close(res, bars, s, entry_i, j, v.tp_pips, "TP")

    if entry_i is None:
        res["outcome"] = "NOT_TOUCHED" if not touched else "OPEN_END"
        return res
    last_exit = c[-1] - (0.0 if is_buy else spr[-1])
    return _close(res, bars, s, entry_i, len(o) - 1, (last_exit - entry_px) / PIP, "TIMEOUT")


def _simulate_layer(res, bars, s, o, h, l, c, spr, is_buy, zero, mid, last, sl_dist, tp_dist) -> dict:
    """Entry bertingkat: 1 unit (0.01 lot) di ZERO, MID, LAST. SL bersama = LAST − SL,
    TP bersama = ZERO + TP. Pips = jumlah semua unit yang ter-fill."""
    levels = (zero, mid, last)
    entries: list[float] = []
    first_i = None
    sl_px = last - sl_dist
    tp_px = zero + tp_dist
    for j in range(len(o)):
        fill_cost = spr[j] if is_buy else 0.0
        exit_adj = 0.0 if is_buy else spr[j]
        new_fill = False
        while len(entries) < 3 and l[j] + fill_cost <= levels[len(entries)]:
            entries.append(min(levels[len(entries)], o[j] + fill_cost))
            new_fill = True
            if first_i is None:
                first_i = j
        if not entries:
            continue
        if l[j] - exit_adj <= sl_px:
            pips = sum(sl_px - e for e in entries) / PIP
            return _close(res, bars, s, first_i, j, pips, "SL", units=len(entries))
        if not new_fill and h[j] - exit_adj >= tp_px:
            pips = sum(tp_px - e for e in entries) / PIP
            return _close(res, bars, s, first_i, j, pips, "TP", units=len(entries))
    if not entries:
        res["outcome"] = "NOT_TOUCHED"
        return res
    last_exit = c[-1] - (0.0 if is_buy else spr[-1])
    return _close(res, bars, s, first_i, len(o) - 1, sum(last_exit - e for e in entries) / PIP,
                  "TIMEOUT", units=len(entries))


_SPACE_CACHE: dict[tuple[int, bool, int], tuple] = {}


def _full_space(bars: Bars, is_buy: bool, tf: int):
    """Array OHLC seluruh data (M1 atau M5) dalam ruang BUY; SELL dinegasikan. Di-cache."""
    key = (id(bars), is_buy, tf)
    if key not in _SPACE_CACHE:
        if tf == 1:
            o, h, l, c = bars.o, bars.h, bars.l, bars.c
        else:
            m = bars.m5
            o, h, l, c = m["open"], m["high"], m["low"], m["close"]
        _SPACE_CACHE[key] = (o, h, l, c) if is_buy else (-o, -l, -h, -c)
    return _SPACE_CACHE[key]


def _close(res: dict, bars: Bars, s: int, entry_j: int, exit_j: int, pips: float, outcome: str,
           units: int = 1) -> dict:
    res["outcome"] = outcome
    res["pips"] = round(pips, 2)
    res["units"] = units
    res["entry_time"] = pd.Timestamp(bars.t[s + entry_j], tz="UTC")
    res["exit_time"] = pd.Timestamp(bars.t[s + exit_j], tz="UTC")
    return res


# ── Ringkasan ───────────────────────────────────────────────────────────────
def summarize(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, g in trades.groupby("variant", sort=False):
        filled = g[g["outcome"].isin(["TP", "SL", "TIMEOUT"])].sort_values("entry_time")
        wins = (filled["pips"] > 0).sum()
        gross_win = filled.loc[filled["pips"] > 0, "pips"].sum()
        gross_loss = -filled.loc[filled["pips"] < 0, "pips"].sum()
        eq = filled["pips"].cumsum()
        dd = (eq.cummax().clip(lower=0) - eq).max() if len(eq) else 0.0
        days = max(1, g["time"].dt.date.nunique())
        oc = Counter(g["outcome"])
        rows.append({
            "variant": name,
            "signals": len(g),
            "trades": len(filled),
            "trades/day": round(len(filled) / days, 1),
            "expired": oc["EXPIRED_TP"] + oc["EXPIRED_SL"],
            "not_touched": oc["NOT_TOUCHED"],
            "winrate%": round(100 * wins / len(filled), 1) if len(filled) else 0.0,
            "total_pips": round(filled["pips"].sum(), 1),
            "avg_pips": round(filled["pips"].mean(), 2) if len(filled) else 0.0,
            "PF": round(gross_win / gross_loss, 2) if gross_loss else float("inf"),
            "maxDD_pips": round(float(dd), 1),
            "usd_0.01lot": round(filled["pips"].sum() * settings.USD_PER_PIP_001, 2),
        })
    return pd.DataFrame(rows)


def default_variants(include_m5: bool = False) -> list[Variant]:
    tps = (10, 20, 30)
    vs = [Variant(e, 1, tp, sl) for sl in ("entry", "zone") for e in ("ZERO", "MID", "LAST") for tp in tps]
    vs += [Variant("LAYER", 1, tp, "zone") for tp in tps]
    tfs = (1, 5) if include_m5 else (1,)
    vs += [Variant(e, tf, tp, sl) for sl in ("entry", "zone") for e in ("FVG", "OB", "OBIM")
           for tf in tfs for tp in tps]
    return vs


# ── Validasi vs laporan provider ────────────────────────────────────────────
def replay_provider(sig: Signal, bars: Bars, tp_pips: float, tp_from: str) -> str | None:
    """Tiru label provider: kedalaman zona yang tercapai + TP/SL.
    tp_from = 'depth' (TP dihitung dari level terdalam) | 'zero' (TP selalu dari zero)."""
    s = bars.first_bar_after(sig.time)
    if s <= 0 or s >= bars.n:
        return None
    zone = resolve_zone(sig.direction, sig.level_first, sig.level_last, ref=bars.o[s - 1])
    if zone.distance > settings.TG_MAX_ZONE_DISTANCE:
        return None
    o, h, l, c, spr, is_buy = _space(bars, sig.direction, s, min(bars.n, s + HORIZON_BARS))
    sgn = 1 if is_buy else -1
    zero, last = sgn * zone.zero, sgn * zone.last
    names = ("ZERO", "MID", "LAST")
    levels = (zero, (zero + last) / 2, last)
    depth = -1                                    # indeks level terdalam yang sudah tersentuh
    for j in range(len(o)):
        while depth < 2 and l[j] <= levels[depth + 1]:
            depth += 1
        if depth < 0:
            continue
        if l[j] <= last - sig.sl_pips * PIP:
            return "LAST-SL"
        base = levels[depth] if tp_from == "depth" else zero
        if h[j] >= base + tp_pips * PIP:
            return f"{names[depth]}-TP"
    return None


def validate(store: Store, signals: list[Signal], bars: Bars, tz_hours: int) -> None:
    by_day: dict[str, list[Signal]] = {}
    for sg in signals:
        d = (sg.time + timedelta(hours=tz_hours)).date().isoformat()
        by_day.setdefault(d, []).append(sg)
    rep = store.conn.execute(
        """SELECT r.report_date, r.seq, r.direction, r.level_first, r.depth, r.outcome
           FROM report_lines r JOIN (SELECT report_date, MAX(message_id) mid FROM report_lines
           GROUP BY report_date) x ON r.message_id = x.mid ORDER BY r.report_date, r.seq""").fetchall()
    rep_day: dict[str, list] = {}
    for r in rep:
        rep_day.setdefault(r["report_date"], []).append(r)

    pairs = []
    for d, sigs in by_day.items():
        lines = rep_day.get(d)
        if not lines:
            continue
        for sg, ln in zip(sigs, lines):
            if sg.direction == ln["direction"] and sg.level_first % 100 == ln["level_first"] % 100:
                pairs.append((sg, f"{ln['depth']}-{ln['outcome']}"))
    total_lines = sum(len(rep_day.get(d, [])) for d in by_day)
    print(f"Zona waktu laporan UTC+{tz_hours}: {len(pairs)} sinyal cocok dengan baris laporan "
          f"(dari {total_lines} baris di rentang data)")
    if not pairs:
        return
    for tp_from in ("depth", "zero"):
        for tp in (10, 20):
            agree = Counter()
            for sg, label in pairs:
                sim = replay_provider(sg, bars, tp, tp_from)
                agree[(label, sim)] += 1
            ok = sum(n for (a, b), n in agree.items() if a == b)
            print(f"  hipotesis TP{tp} dari {tp_from:<5}: cocok {ok}/{len(pairs)} = {100 * ok / len(pairs):.1f}%")
    labels = Counter(lbl for _, lbl in pairs)
    print("  distribusi label provider (sinyal cocok):", dict(labels))


def check_offset(signals: list[Signal], df: pd.DataFrame) -> None:
    """Median jarak harga saat pesan ke zona, untuk berbagai offset jam. Terkecil = offset benar."""
    for off in range(-3, 4):
        d = []
        shifted = df.copy()
        shifted.index = shifted.index - pd.Timedelta(hours=off)
        b = Bars(shifted)
        for sg in signals[:400]:
            s = b.first_bar_after(sg.time)
            if 0 < s < b.n:
                z = resolve_zone(sg.direction, sg.level_first, sg.level_last, ref=b.o[s - 1])
                d.append(abs(b.o[s - 1] - z.zero))
        print(f"  offset {off:+d} jam: median jarak harga→zero = {np.median(d):.2f}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest sinyal Telegram")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--check-offset", action="store_true")
    ap.add_argument("--report-tz", type=int, default=7, help="zona waktu tanggal laporan (WIB = 7)")
    ap.add_argument("--m5", action="store_true", help="ikutkan konfirmasi M5")
    ap.add_argument("--spread-pips", type=float, default=None,
                    help="ganti spread per bar dengan nilai tetap (pips), mis. 0 untuk edge kotor")
    args = ap.parse_args()

    df = load_m1()
    start = df.index[0].to_pydatetime()
    end = df.index[-1].to_pydatetime()
    store = Store(settings.DB_PATH)
    signals = load_signals(store, start, end)
    print(f"Data M1: {start:%Y-%m-%d} → {end:%Y-%m-%d} | sinyal unik di rentang ini: {len(signals)}")

    if args.check_offset:
        check_offset(signals, df)
        return
    if args.spread_pips is not None:
        df = df.copy()
        df["spread"] = args.spread_pips * PIP
        print(f"Spread dipaksa tetap: {args.spread_pips} pips")
    bars = Bars(df)
    if args.validate:
        for tz in (0, args.report_tz):
            validate(store, signals, bars, tz)
        return

    results = [simulate(sg, v, bars) for v in default_variants(args.m5) for sg in signals]
    trades = pd.DataFrame(results)
    trades.to_csv(settings.DATA_DIR / "backtest_trades.csv", index=False)
    summary = summarize(trades)
    summary.to_csv(settings.DATA_DIR / "backtest_summary.csv", index=False)
    with pd.option_context("display.max_rows", 100, "display.width", 200):
        print(summary.to_string(index=False))
    print(f"\nDisimpan: {settings.DATA_DIR / 'backtest_summary.csv'} dan backtest_trades.csv")


if __name__ == "__main__":
    main()
