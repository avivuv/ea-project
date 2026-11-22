"""
Jurnal trading metode non-Telegram (Swing Donchian, Trend MA Cross, SMC Top-Down, ORB NY) → file Excel (.xlsx).

Sumber:
- Trade: histori deal & order MT5 per magic (entry, SL/TP awal, exit, alasan tutup, USD, R, durasi) +
  posisi yang masih terbuka. MT5 tidak terhubung → CSV trade runner (pro_live_trades.csv, orb_live_trades*.csv).
- Kejadian: log runner (`data/*_live*.log`) — setup (POI armed / opening range), konfirmasi CHoCH, entry,
  skip, pending batal, kelola posisi (breakeven/trailing), tutup, error.

Sheet: Trades · Setup (tiap setup → entry / tidak entry + alasan) · Kejadian · Ringkasan Harian · Ringkasan Metode.

    python -m tg_signal.method_journal --group pro --from 2026-11-11
    python -m tg_signal.method_journal --group swing --out swing.xlsx
"""
from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from tg_signal import settings
from tg_signal.journal import to_xlsx

WIB = timedelta(hours=7)
LOG_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:,\d+)?(Z)?\s+(?:(?:INFO|WARNING|ERROR)\s+)?(.*)$")
ID_RE = re.compile(r"^(?:\(dry\)\s*)?\[([A-Z0-9_]+)\]\s*(.*)$")
TICKET_RE = re.compile(r"\b(\d{8,12})\b")
DIR_RE = re.compile(r"\b(BUY|SELL)\b")

NOISE = ("HTTP Request", "[ForexCalendar]", "START ", " login ", "(dry)")
KINDS = [                    # (pola, jenis) — urutan penting
    ("ERROR", "ERROR"), ("GAGAL", "ERROR"),
    ("SKIP", "SKIP"),
    ("dibatalkan", "BATAL"), ("BATAL", "BATAL"),
    ("TUTUP", "EXIT"), ("TIME STOP", "EXIT"), ("EXIT", "EXIT"), ("CLOSE ", "EXIT"),
    ("BREAKEVEN", "KELOLA"), ("trailing", "KELOLA"),
    ("ARMED", "SETUP"), ("OPENING RANGE", "SETUP"),       # sebelum CHoCH: teks ARMED berisi "tunggu CHoCH"
    ("CHoCH", "KONFIRMASI"),
    ("PENDING TERISI", "TERISI"),
    ("ORDER", "ENTRY"), ("OPEN ", "ENTRY"),
]
NO_ENTRY_TXT = {             # setup tanpa entry → alasan
    "ARMED": "CHoCH M5 tidak terkonfirmasi sebelum POI ditembus / kedaluwarsa (atau risiko di luar batas)",
    "OPENING RANGE": "Tidak ada breakout (close M5 di luar range) dalam batas waktu / bias tidak searah",
}


@dataclass(frozen=True)
class Spec:
    """Satu sub-metode: id, simbol, magic, file log di data/."""
    id: str
    symbol: str
    magic: int
    log: str


def classify(msg: str) -> str | None:
    if any(n in msg for n in NOISE):
        return None
    return next((k for pat, k in KINDS if pat in msg), None)


# ── log runner ──────────────────────────────────────────────────────────────
def log_events(specs: list[Spec], data_dir: Path = settings.DATA_DIR) -> pd.DataFrame:
    """Baris log penting → DataFrame [Waktu (WIB), Metode, Jenis, Arah, Ticket, Keterangan].
    Log berakhiran Z = UTC, log logging Python = jam lokal PC (WIB)."""
    by_log: dict[str, list[Spec]] = {}
    for s in specs:
        by_log.setdefault(s.log, []).append(s)
    ids = {s.id for s in specs}
    rows = []
    for name, ss in by_log.items():
        p = data_dir / name
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = LOG_RE.match(ln)
            if not m:
                continue
            msg = m.group(3).strip()
            kind = classify(msg)
            if not kind:
                continue
            mid = ID_RE.match(msg)
            if mid:
                if mid.group(1) not in ids:
                    continue                            # baris metode lain di log bersama
                method, msg = mid.group(1), mid.group(2)
            elif len(ss) == 1:
                method = ss[0].id
            else:
                method = next((s.id for s in ss if s.symbol in msg), ss[0].id)
            t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") + (WIB if m.group(2) else timedelta())
            d = DIR_RE.search(msg)
            tk = TICKET_RE.search(msg)
            rows.append({"Waktu (WIB)": t, "Metode": method, "Jenis": kind, "Arah": d.group(1) if d else "",
                         "Ticket": int(tk.group(1)) if tk else None, "Keterangan": msg})
    cols = ["Waktu (WIB)", "Metode", "Jenis", "Arah", "Ticket", "Keterangan"]
    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values("Waktu (WIB)", kind="stable").reset_index(drop=True) if not df.empty else df


def setups(ev: pd.DataFrame) -> pd.DataFrame:
    """Tiap SETUP dipasangkan dengan ENTRY metode (& arah) yang sama sebelum setup berikutnya."""
    cols = ["Waktu (WIB)", "Metode", "Arah", "Setup", "Keputusan", "Alasan / entry", "Ticket"]
    if ev.empty:
        return pd.DataFrame(columns=cols)
    out = []
    recs = ev.to_dict("records")
    for i, e in enumerate(recs):
        if e["Jenis"] != "SETUP":
            continue
        same = lambda x: x["Metode"] == e["Metode"] and (not e["Arah"] or not x["Arah"] or x["Arah"] == e["Arah"])
        conf, entry = None, None
        for x in recs[i + 1:]:
            if not same(x):
                continue
            if x["Jenis"] == "SETUP" and (x["Arah"] == e["Arah"] or not e["Arah"]):
                break
            if x["Jenis"] == "KONFIRMASI" and conf is None:
                conf = x
            if x["Jenis"] == "ENTRY":
                entry = x
                break
        if entry is not None:
            why = entry["Keterangan"] + (f" · {conf['Keterangan']}" if conf is not None else "")
            dec, tk = "ENTRY", entry["Ticket"]
        else:
            key = next((k for k in NO_ENTRY_TXT if k in e["Keterangan"]), None)
            why = (f"{conf['Keterangan']} → tidak jadi order" if conf is not None
                   else NO_ENTRY_TXT.get(key, "Tidak ada entry"))
            dec, tk = "TIDAK ENTRY", None
        out.append({"Waktu (WIB)": e["Waktu (WIB)"], "Metode": e["Metode"], "Arah": e["Arah"],
                    "Setup": e["Keterangan"], "Keputusan": dec, "Alasan / entry": why, "Ticket": tk})
    return pd.DataFrame(out, columns=cols)


# ── trade ───────────────────────────────────────────────────────────────────
def mt5_trades(specs: list[Spec], since: datetime) -> list[dict] | None:
    """Posisi (tutup & terbuka) dari MT5 untuk magic `specs`. None bila MT5 tidak terhubung."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(**settings.mt5_init_kwargs()):
            return None
    except Exception:
        return None
    off = timedelta(hours=settings.MT5_UTC_OFFSET_H)
    utc = lambda ts: datetime.fromtimestamp(ts, timezone.utc) - off      # noqa: E731
    by_magic = {s.magic: s for s in specs}
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(since - timedelta(days=1), now + timedelta(days=1)) or ()
    orders = mt5.history_orders_get(since - timedelta(days=1), now + timedelta(days=1)) or ()
    first_order: dict[int, object] = {}
    for o in sorted(orders, key=lambda o: o.time_setup):
        if o.position_id and o.position_id not in first_order:
            first_order[o.position_id] = o
    by_pos: dict[int, list] = {}
    for d in deals:
        if d.position_id:
            by_pos.setdefault(d.position_id, []).append(d)
    why = {mt5.DEAL_REASON_TP: "TP", mt5.DEAL_REASON_SL: "SL", mt5.DEAL_REASON_EXPERT: "Ditutup EA",
           mt5.DEAL_REASON_CLIENT: "Manual", mt5.DEAL_REASON_MOBILE: "Manual (HP)",
           mt5.DEAL_REASON_SO: "Stop out"}
    out = []
    for pid, ds in by_pos.items():
        ins = [d for d in ds if d.entry == mt5.DEAL_ENTRY_IN]
        outs = [d for d in ds if d.entry == mt5.DEAL_ENTRY_OUT]
        if not ins or ins[0].magic not in by_magic:
            continue
        if sum(d.volume for d in outs) + 1e-9 < sum(d.volume for d in ins):
            continue                                    # masih terbuka → dari positions_get
        o0 = first_order.get(pid)
        last = outs[-1]
        out.append({"ticket": pid, "method": by_magic[ins[0].magic].id, "symbol": ins[0].symbol,
                    "dir": "BUY" if ins[0].type == mt5.DEAL_TYPE_BUY else "SELL",
                    "lot": sum(d.volume for d in ins), "open": utc(ins[0].time), "entry": ins[0].price,
                    "sl": o0.sl if o0 and o0.sl else None, "tp": o0.tp if o0 and o0.tp else None,
                    "close": utc(last.time), "exit": last.price, "why": why.get(last.reason, "Lainnya"),
                    "usd": sum(x.profit + x.swap + x.commission for x in ds)})
    for p in mt5.positions_get() or ():
        if p.magic not in by_magic:
            continue
        o0 = first_order.get(p.ticket)
        out.append({"ticket": p.ticket, "method": by_magic[p.magic].id, "symbol": p.symbol,
                    "dir": "BUY" if p.type == 0 else "SELL", "lot": p.volume, "open": utc(p.time),
                    "entry": p.price_open, "sl": (o0.sl if o0 and o0.sl else p.sl) or None, "tp": p.tp or None,
                    "close": None, "exit": p.price_current, "why": "Masih terbuka", "usd": p.profit + p.swap})
    return [t for t in out if t["open"] >= since or t["close"] is None or t["close"] >= since]


def csv_trades(specs: list[Spec], data_dir: Path = settings.DATA_DIR) -> list[dict]:
    """Cadangan saat MT5 tidak terhubung: CSV trade tutup yang ditulis runner (hanya SMC & ORB)."""
    files = []
    for s in specs:
        if s.log.startswith("pro_live"):
            files.append((s, data_dir / "pro_live_trades.csv"))
        elif s.log.startswith("orb_live"):
            files.append((s, data_dir / s.log.replace("orb_live", "orb_live_trades").replace(".log", ".csv")))
    out = []
    for s, f in files:
        if not f.exists():
            continue
        with f.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("mode") != "DEMO":
                    continue
                ts = lambda v: pd.Timestamp(v).tz_convert("UTC").to_pydatetime() if v else None  # noqa: E731
                out.append({"ticket": int(r["ticket"]) if r.get("ticket") else None, "method": s.id,
                            "symbol": s.symbol, "dir": r["dir"], "lot": float(r["lot"]) if r.get("lot") else None,
                            "open": ts(r["placed"]), "entry": float(r["entry"]), "sl": float(r["sl"]),
                            "tp": float(r["tp"]), "close": ts(r["closed"]), "exit": float(r["exit"]),
                            "why": r.get("outcome", ""), "usd": float(r["usd"])})
    return out


def _r(t: dict) -> float | None:
    if not t["sl"] or t["exit"] is None:
        return None
    risk = abs(t["entry"] - t["sl"])
    if risk <= 0:
        return None
    sg = 1 if t["dir"] == "BUY" else -1
    return round(sg * (t["exit"] - t["entry"]) / risk, 2)


# ── frames ──────────────────────────────────────────────────────────────────
def build_frames(specs: list[Spec], start: date | None = None, end: date | None = None,
                 trades: list[dict] | None = None, data_dir: Path = settings.DATA_DIR) -> dict[str, pd.DataFrame]:
    """trades None → ambil dari MT5 (cadangan: CSV runner)."""
    def ok(t: datetime | None) -> bool:
        return t is not None and (start is None or t.date() >= start) and (end is None or t.date() <= end)

    ev = log_events(specs, data_dir)
    if not ev.empty:
        ev = ev[ev["Waktu (WIB)"].map(ok)].reset_index(drop=True)
    st = setups(ev)
    src = "MT5"
    if trades is None:
        since = datetime.combine(start, datetime.min.time(), timezone.utc) - WIB if start else \
            datetime.now(timezone.utc) - timedelta(days=365)
        trades = mt5_trades(specs, since)
        if trades is None:
            trades, src = csv_trades(specs, data_dir), "CSV runner (MT5 tidak terhubung)"

    wib = lambda x: (x + WIB).replace(tzinfo=None) if x else None       # noqa: E731
    entry_of = {}
    if not ev.empty:
        for e in ev[ev["Jenis"].isin(["ENTRY", "TERISI"]) & ev["Ticket"].notna()].itertuples():
            entry_of.setdefault(int(e.Ticket), e.Keterangan)
    conf_of = {}
    for r in st[st["Keputusan"] == "ENTRY"].itertuples():
        if r.Ticket is not None and r.Ticket == r.Ticket:
            conf_of[int(r.Ticket)] = r.Setup
    rows = []
    for t in sorted(trades, key=lambda t: t["open"]):
        txt = entry_of.get(t["ticket"], "")
        for k in ("sl", "tp"):                          # SL/TP awal tidak ada di histori → dari baris ORDER
            m = re.search(rf"\b{k.upper()} (\d+(?:\.\d+)?)", txt)
            if not t[k] and m:
                t = {**t, k: float(m.group(1))}
        t_open = wib(t["open"])
        if not (ok(t_open) or (t["close"] is None and (end is None or t_open.date() <= end))):
            continue
        rows.append({
            "Jam open": t_open, "Jam close": wib(t["close"]), "Metode": t["method"], "Simbol": t["symbol"],
            "Ticket": t["ticket"], "Arah": t["dir"], "Lot": t["lot"], "Entry": t["entry"], "SL": t["sl"],
            "TP": t["tp"], "Exit": t["exit"], "Hasil": t["why"], "Profit USD": round(t["usd"], 2), "R": _r(t),
            "Durasi (menit)": round((t["close"] - t["open"]).total_seconds() / 60, 1) if t["close"] else None,
            "Setup": conf_of.get(t["ticket"], ""), "Alasan entry": entry_of.get(t["ticket"], ""),
        })
    tcols = ["Jam open", "Jam close", "Metode", "Simbol", "Ticket", "Arah", "Lot", "Entry", "SL", "TP", "Exit",
             "Hasil", "Profit USD", "R", "Durasi (menit)", "Setup", "Alasan entry"]
    trd = pd.DataFrame(rows, columns=tcols)
    return {"Trades": trd, "Setup": st, "Kejadian": ev, "Ringkasan Harian": _daily(trd, ev),
            "Ringkasan Metode": _per_method(trd, specs, src)}


def _daily(trd: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    cols = ["Tanggal", "Jml setup", "Entry", "Skip/batal", "Trade tutup", "Win", "Loss", "Win rate %", "Profit USD",
            "Kumulatif USD"]
    days: dict[date, dict] = {}
    blank = lambda: {k: 0 for k in cols[1:]}                           # noqa: E731
    for e in ev.to_dict("records"):
        d = days.setdefault(e["Waktu (WIB)"].date(), blank())
        d["Jml setup"] += e["Jenis"] == "SETUP"
        d["Entry"] += e["Jenis"] == "ENTRY"
        d["Skip/batal"] += e["Jenis"] in ("SKIP", "BATAL")
    for t in trd.to_dict("records"):
        if t["Jam close"] is None or t["Jam close"] != t["Jam close"]:
            continue                                    # masih terbuka
        d = days.setdefault(t["Jam close"].date(), blank())
        d["Trade tutup"] += 1
        d["Win"] += t["Profit USD"] > 0
        d["Loss"] += t["Profit USD"] <= 0
        d["Profit USD"] += t["Profit USD"]
    if not days:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame([{"Tanggal": k, **v} for k, v in sorted(days.items())], columns=cols)
    df["Win rate %"] = [round(100 * w / (w + l), 1) if w + l else None for w, l in zip(df["Win"], df["Loss"])]
    df["Profit USD"] = df["Profit USD"].astype(float).round(2)
    df["Kumulatif USD"] = df["Profit USD"].cumsum().round(2)
    tot = {"Tanggal": "TOTAL", **{k: df[k].sum() for k in cols[1:7] + ["Profit USD"]}}
    tot["Win rate %"] = round(100 * tot["Win"] / (tot["Win"] + tot["Loss"]), 1) if tot["Win"] + tot["Loss"] else None
    tot["Profit USD"] = round(float(tot["Profit USD"]), 2)
    return pd.concat([df, pd.DataFrame([tot])], ignore_index=True)


def _per_method(trd: pd.DataFrame, specs: list[Spec], src: str) -> pd.DataFrame:
    out = []
    for s in specs:
        g = trd[(trd["Metode"] == s.id) & trd["Jam close"].notna()] if not trd.empty else trd
        win, loss = g[g["Profit USD"] > 0], g[g["Profit USD"] <= 0]
        gl = -loss["Profit USD"].sum()
        out.append({"Metode": s.id, "Simbol": s.symbol, "Magic": s.magic,
                    "Terbuka": int(((trd["Metode"] == s.id) & trd["Jam close"].isna()).sum()) if not trd.empty else 0,
                    "Trade tutup": len(g), "Win": len(win), "Loss": len(loss),
                    "Win rate %": round(100 * len(win) / len(g), 1) if len(g) else None,
                    "Profit USD": round(float(g["Profit USD"].sum()), 2),
                    "Rata² R": round(float(g["R"].mean()), 2) if g["R"].notna().any() else None,
                    "Profit factor": round(float(win["Profit USD"].sum() / gl), 2) if gl > 0 else None,
                    "Sumber trade": src})
    return pd.DataFrame(out)


def export(title: str, specs: list[Spec], start: date | None = None, end: date | None = None) -> tuple[bytes, str]:
    """(isi .xlsx, nama file) — dipakai CLI dan dashboard."""
    frames = build_frames(specs, start, end)
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return to_xlsx(frames), f"jurnal_{slug}_{start or 'awal'}_{end or 'sekarang'}.xlsx"


def main() -> None:
    from tg_signal.dashboard import GROUPS                          # konfigurasi metode ada di dashboard
    groups = {g.key: g for g in GROUPS if g.key != "tg"}
    ap = argparse.ArgumentParser(description="Ekspor jurnal trading metode (Swing/MA Cross/SMC/ORB) ke .xlsx")
    ap.add_argument("--group", required=True, choices=sorted(groups))
    ap.add_argument("--from", dest="start", type=date.fromisoformat, help="tanggal awal WIB (YYYY-MM-DD)")
    ap.add_argument("--to", dest="end", type=date.fromisoformat, help="tanggal akhir WIB (YYYY-MM-DD)")
    ap.add_argument("--out", type=Path, help="file keluaran (default data/<nama otomatis>)")
    a = ap.parse_args()
    g = groups[a.group]
    data, name = export(g.tab, [Spec(m.id, m.symbol, m.magic, m.log) for m in g.methods], a.start, a.end)
    out = a.out or settings.DATA_DIR / name
    out.write_bytes(data)
    print(f"jurnal tersimpan: {out}")


if __name__ == "__main__":
    main()
