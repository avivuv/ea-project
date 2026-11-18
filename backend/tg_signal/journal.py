"""
Jurnal trading EA sinyal Telegram → file Excel (.xlsx).

Satu baris per sinyal: keputusan (ENTRY / SKIP / MENUNGGU), alasan dalam bahasa manusia, POI yang terdeteksi,
alur status, detail trade (entry/SL/TP/exit/pips/USD/R) dan perkiraan hasil versi admin (dari pesan Report).

Sumber: database SQLite (dibuka read-only) + `data/live.log` untuk detail POI yang tidak disimpan di DB.

    python -m tg_signal.journal                          # semua sinyal yang sudah diproses runner
    python -m tg_signal.journal --from 2026-11-11 --to 2026-11-18 --mode DEMO --out jurnal.xlsx
"""
from __future__ import annotations

import argparse
import io
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from tg_signal import settings

WIB = timedelta(hours=settings.TG_DAY_TZ_HOURS)
PIP = 0.10
LOG_PATH = settings.DATA_DIR / "live.log"

DECISION = {"OPEN": "ENTRY", "CLOSED": "ENTRY", "PENDING": "MENUNGGU", "WAITING": "MENUNGGU",
            "REJECTED": "SKIP", "EXPIRED": "SKIP", "CANCELLED": "SKIP", "NEW": "BELUM DIPROSES"}

REASON_TXT = {
    "DUPLICATE": "Sinyal dobel (arah & zona sama baru saja diproses)",
    "PAUSED": "EA sedang di-pause",
    "PRICE_STALE": "Harga MT5 tidak update (basi)",
    "ZONE_TOO_FAR": "Zona terlalu jauh dari harga saat sinyal masuk",
    "SPREAD_TOO_WIDE": "Spread terlalu lebar",
    "DAILY_LOSS_LIMIT": "Batas rugi harian tercapai",
    "DAILY_PROFIT_TARGET": "Target profit harian tercapai",
    "MAX_TRADES_DAY": "Jumlah trade maksimal per hari tercapai",
    "MAX_POSITIONS": "Jumlah posisi terbuka maksimal tercapai",
    "DUPLICATE_OPEN": "Sudah ada posisi searah di zona yang sama",
    "PAST_SL": "Harga sudah melewati LAST ∓ SL saat sinyal masuk",
}

OUTCOME_TXT = {"TP": "TP", "SL": "SL", "TP_ADMIN": "TP admin (dipotong)", "TARGET": "Target harian (tutup semua)",
               "MANUAL": "Ditutup manual", "OTHER": "Lainnya"}


def human_reason(reason: str) -> str:
    """Kode alasan runner → kalimat. Alasan yang sudah berupa kalimat dikembalikan apa adanya."""
    r = (reason or "").strip()
    if r.startswith("ORDER_FAILED"):
        return "Order ditolak MT5: " + r.split(":", 1)[-1].strip()
    return REASON_TXT.get(r, r)


SKIP_CATEGORY = [            # (pola di alasan, kategori) — urutan penting
    ("admin sudah TP", "Admin sudah TP sebelum entry"),
    ("TP admin", "TP admin tercapai sebelum entry"),
    ("TP tercapai", "TP tercapai sebelum entry"),
    ("melewati LAST", "Harga lewat SL zona sebelum entry"),
    ("diganti sinyal", "Pending diganti sinyal baru"),
    ("diedit admin", "Pesan sinyal diedit admin"),
    ("Order ditolak", "Order ditolak MT5"),
    ("gagal pindah", "Order ditolak MT5"),
    ("order hilang", "Pending hilang dari MT5"),
    ("target profit", "Target profit harian tercapai"),
]


def skip_category(reason: str) -> str:
    low = reason.lower()
    return next((cat for pat, cat in SKIP_CATEGORY if pat.lower() in low), reason)


def entry_choice(choice: str) -> str:
    """Segmen log pilihan entry → kalimat singkat."""
    if choice.startswith("di zona"):
        return "harga sudah di dalam zona"
    if choice.startswith("harga sudah menembus"):
        return "harga menembus harga limit sebelum order terpasang"
    return choice.replace("POI terbentuk: ", "")


def to_wib(iso: str | None) -> datetime | None:
    if not iso:
        return None
    return (datetime.fromisoformat(iso) + WIB).replace(tzinfo=None)


# ── detail dari live.log ────────────────────────────────────────────────────
_SIG_RE = re.compile(r"sinyal #(s?\d+) .*?→ zona \S+ \| (.*)$")


def log_notes(path: Path = LOG_PATH) -> dict[str, list[str]]:
    """{'<msg_id>' atau 's<signal_id>': [segmen catatan setelah zona, ...]} dari baris `sinyal #...` di live.log."""
    out: dict[str, list[str]] = defaultdict(list)
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _SIG_RE.search(line)
        if m:
            out[m.group(1)].extend(s.strip() for s in m.group(2).split(" | ") if s.strip())
    return out


def split_notes(notes: list[str]) -> tuple[str, str]:
    """(POI yang terdeteksi di zona, pilihan entry) dari segmen log satu sinyal (yang terakhir dipakai)."""
    pois, choice = "", ""
    for s in notes:
        if s.startswith("POI di zona:"):
            pois = s.split(":", 1)[1].strip()
        elif s.startswith(("POI ", "POI terbentuk", "di zona", "tanpa POI", "harga sudah")):
            choice = s
    return pois, choice


# ── hasil versi admin (Report harian) ───────────────────────────────────────
def admin_results(con: sqlite3.Connection, sigs: list[sqlite3.Row]) -> dict[int, str]:
    """Perkiraan hasil admin per sinyal: baris Report hari itu dicocokkan berurutan ke kiriman sinyal
    arah+level sama di tanggal WIB yang sama (kiriman dobel ≤ 5 menit dianggap satu)."""
    lines = con.execute("""
        SELECT rl.* FROM report_lines rl JOIN (
            SELECT report_date, message_id FROM (
                SELECT report_date, message_id, COUNT(*) n,
                       ROW_NUMBER() OVER (PARTITION BY report_date ORDER BY COUNT(*) DESC, message_id DESC) rk
                FROM report_lines GROUP BY report_date, message_id) WHERE rk = 1
        ) last ON last.message_id = rl.message_id AND last.report_date = rl.report_date
        ORDER BY rl.report_date, rl.seq""").fetchall()
    # kelompok kiriman per (tanggal, arah, level)
    groups: dict[tuple, list[list[sqlite3.Row]]] = defaultdict(list)
    for s in sigs:
        t = to_wib(s["received_utc"])
        key = (t.date().isoformat(), s["direction"], s["level_first"], s["level_last"])
        g = groups[key]
        if g and (t - to_wib(g[-1][-1]["received_utc"])).total_seconds() <= 300:
            g[-1].append(s)
        else:
            g.append([s])
    used: Counter = Counter()
    out: dict[int, str] = {}
    for ln in lines:
        cands = [k for k in groups if k[0] == ln["report_date"] and k[1] == ln["direction"]
                 and k[2] == ln["level_first"] and (ln["level_last"] is None or k[3] == ln["level_last"])]
        for k in cands:
            if used[k] < len(groups[k]):
                txt = ("" if ln["win"] is None else ("✅ " if ln["win"] else "❌ ")) + f"{ln['depth']}-{ln['outcome']}"
                for s in groups[k][used[k]]:
                    out[s["id"]] = txt
                used[k] += 1
                break
    return out


# ── data ────────────────────────────────────────────────────────────────────
def connect(path: Path | str = settings.DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def build_frames(con: sqlite3.Connection, start: date | None = None, end: date | None = None,
                 mode: str | None = None, include_new: bool = False,
                 log_path: Path = LOG_PATH) -> dict[str, pd.DataFrame]:
    """DataFrame untuk tiap sheet: Jurnal, Trades, Ringkasan Harian, Alasan Skip."""
    sigs = con.execute("""SELECT s.*, m.msg_id, m.text AS msg_text, m.edit_utc FROM signals s
                          JOIN messages m ON m.id = s.message_id ORDER BY s.received_utc""").fetchall()
    admin = admin_results(con, sigs)

    def in_range(iso: str) -> bool:
        d = to_wib(iso).date()
        return (start is None or d >= start) and (end is None or d <= end)

    sigs = [s for s in sigs if in_range(s["received_utc"]) and (include_new or s["status"] != "NEW")]
    events: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for e in con.execute("SELECT * FROM signal_events ORDER BY ts_utc, id"):
        events[e["signal_id"]].append(e)
    trades: dict[int, list[sqlite3.Row]] = defaultdict(list)
    q = "SELECT * FROM trades" + (" WHERE mode=?" if mode else "") + " ORDER BY open_utc"
    for t in con.execute(q, (mode,) if mode else ()):
        trades[t["signal_id"]].append(t)
    notes = log_notes(log_path)

    rows, trade_rows = [], []
    for s in sigs:
        evs = events.get(s["id"], [])
        tr = trades.get(s["id"], [])
        if mode and not tr and s["status"] in ("OPEN", "CLOSED"):
            continue                                    # entry di mode lain
        t = tr[-1] if tr else None
        decision = DECISION.get(s["status"], s["status"])
        pois, choice = split_notes(notes.get(str(s["msg_id"]), []) + notes.get(f"s{s['id']}", []))
        was_pending = any(e["to_status"] == "PENDING" for e in evs)
        if decision == "ENTRY":
            how = "Limit terisi" if was_pending and t is not None and "market" not in choice else "Market"
            reason = f"{how} — {entry_choice(choice)}" if choice else how
            if any(e["to_status"] == "WAITING" for e in evs):
                reason += " (setelah menunggu POI)"
        elif decision == "SKIP":
            reason = human_reason(s["status_reason"])
        elif decision == "MENUNGGU":
            reason = human_reason(s["status_reason"]) + (f" — {choice}" if choice else "")
        else:
            reason = "Sinyal sebelum runner aktif / belum diproses"
        flow = " › ".join(f"{to_wib(e['ts_utc']):%d/%m %H:%M} {e['to_status']}"
                          + (f" ({human_reason(e['reason'])})" if e["reason"] else "") for e in evs)
        rec = {
            "Tanggal": to_wib(s["received_utc"]).date(),
            "Jam sinyal": to_wib(s["received_utc"]),
            "Msg ID": s["msg_id"],
            "Arah": s["direction"],
            "Sinyal": f"{s['level_first']:02d}-{s['level_last']:02d}" + (" (diedit)" if s["edit_utc"] else ""),
            "Harga saat sinyal": s["ref_price"],
            "ZERO": s["zero"],
            "LAST": s["last"],
            "Keputusan": decision,
            "Alasan entry / skip": reason,
            "Kategori skip": skip_category(reason) if decision == "SKIP" else "",
            "POI terdeteksi di zona": pois,
            "Status akhir": s["status"],
            "Alur status": flow,
            "Mode": t["mode"] if t else None,
            "Ticket": t["ticket"] if t else None,
            "Jam open": to_wib(t["open_utc"]) if t else None,
            "Entry": t["entry"] if t else None,
            "SL": t["sl"] if t else None,
            "TP": t["tp"] if t else None,
            "Jam close": to_wib(t["close_utc"]) if t and t["close_utc"] else None,
            "Exit": t["exit"] if t else None,
            "Hasil": OUTCOME_TXT.get(t["outcome"], t["outcome"]) if t and t["outcome"] else
                     ("Masih terbuka" if t else None),
            "Pips": t["pips"] if t else None,
            "Profit USD": t["profit_usd"] if t else None,
            "R": _r(t),
            "Durasi (menit)": _dur(t),
            "Hasil admin (perkiraan)": admin.get(s["id"], ""),
            "Pesan sinyal": (s["msg_text"] or "").strip()[:300],
        }
        rows.append(rec)
        for x in tr:
            trade_rows.append({
                "Jam open": to_wib(x["open_utc"]), "Jam close": to_wib(x["close_utc"]), "Mode": x["mode"],
                "Ticket": x["ticket"], "Msg ID": s["msg_id"], "Sinyal": f"{s['direction']} {rec['Sinyal']}",
                "Arah": x["direction"], "Lot": x["lot"], "Entry": x["entry"], "SL": x["sl"], "TP": x["tp"],
                "Exit": x["exit"], "Hasil": OUTCOME_TXT.get(x["outcome"], x["outcome"]) if x["outcome"] else "Masih terbuka",
                "Pips": x["pips"], "Profit USD": x["profit_usd"], "R": _r(x), "Durasi (menit)": _dur(x),
                "Alasan entry": reason if x is t else "",
                "Hasil admin (perkiraan)": rec["Hasil admin (perkiraan)"],
            })

    jur = pd.DataFrame(rows)
    trd = pd.DataFrame(trade_rows)
    return {"Jurnal": jur, "Trades": trd, "Ringkasan Harian": _daily(jur, trd), "Alasan Skip": _skips(jur)}


def _r(t) -> float | None:
    if t is None or t["pips"] is None or not t["sl"]:
        return None
    risk = abs(t["entry"] - t["sl"]) / PIP
    return round(t["pips"] / risk, 2) if risk > 0 else None


def _dur(t) -> float | None:
    if t is None or not t["close_utc"]:
        return None
    return round((datetime.fromisoformat(t["close_utc"]) - datetime.fromisoformat(t["open_utc"])).total_seconds() / 60, 1)


def _daily(jur: pd.DataFrame, trd: pd.DataFrame) -> pd.DataFrame:
    cols = ["Tanggal", "Sinyal", "Entry", "Skip", "Menunggu", "Trade tutup", "Win", "Loss", "Win rate %",
            "Pips", "Profit USD", "Kumulatif USD"]
    if jur.empty:
        return pd.DataFrame(columns=cols)
    out = []
    closed = trd[trd["Jam close"].notna()].copy() if not trd.empty else pd.DataFrame(columns=["Jam close"])
    if not closed.empty:
        closed["Tanggal"] = pd.to_datetime(closed["Jam close"]).dt.date
    for d, g in jur.groupby("Tanggal"):
        c = closed[closed["Tanggal"] == d] if not closed.empty else closed
        win = int((c["Profit USD"] > 0).sum()) if not c.empty else 0
        loss = int((c["Profit USD"] < 0).sum()) if not c.empty else 0
        out.append({
            "Tanggal": d, "Sinyal": len(g), "Entry": int((g["Keputusan"] == "ENTRY").sum()),
            "Skip": int((g["Keputusan"] == "SKIP").sum()), "Menunggu": int((g["Keputusan"] == "MENUNGGU").sum()),
            "Trade tutup": len(c), "Win": win, "Loss": loss,
            "Win rate %": round(100 * win / (win + loss), 1) if win + loss else None,
            "Pips": round(float(c["Pips"].sum()), 1) if not c.empty else 0.0,
            "Profit USD": round(float(c["Profit USD"].sum()), 2) if not c.empty else 0.0,
        })
    df = pd.DataFrame(out, columns=cols[:-1])
    df["Kumulatif USD"] = df["Profit USD"].cumsum().round(2)
    tot = {"Tanggal": "TOTAL", **{k: df[k].sum() for k in ["Sinyal", "Entry", "Skip", "Menunggu", "Trade tutup",
                                                           "Win", "Loss", "Pips", "Profit USD"]}}
    tot["Win rate %"] = round(100 * tot["Win"] / (tot["Win"] + tot["Loss"]), 1) if tot["Win"] + tot["Loss"] else None
    tot["Pips"], tot["Profit USD"] = round(tot["Pips"], 1), round(tot["Profit USD"], 2)
    return pd.concat([df, pd.DataFrame([tot])], ignore_index=True)


def _skips(jur: pd.DataFrame) -> pd.DataFrame:
    if jur.empty:
        return pd.DataFrame(columns=["Alasan", "Jumlah", "%"])
    sk = jur[jur["Keputusan"] == "SKIP"]["Kategori skip"].value_counts()
    return pd.DataFrame({"Alasan": sk.index, "Jumlah": sk.values,
                         "%": (100 * sk.values / max(sk.sum(), 1)).round(1)})


# ── Excel ───────────────────────────────────────────────────────────────────
WIDE = {"Alasan entry / skip": 48, "POI terdeteksi di zona": 40, "Alur status": 70, "Pesan sinyal": 40,
        "Alasan entry": 48, "Alasan": 60}
PRICE_COLS = {"Harga saat sinyal", "ZERO", "LAST", "Entry", "SL", "TP", "Exit"}
FILL = {"ENTRY": "D9F2D9", "SKIP": "EEEEEE", "MENUNGGU": "FFF2CC"}


def to_xlsx(frames: dict[str, pd.DataFrame]) -> bytes:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in frames.items():
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            if ws.max_row > 1:
                ws.auto_filter.ref = ws.dimensions
            head_fill = PatternFill("solid", fgColor="1F3A5F")
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = head_fill
                c.alignment = Alignment(vertical="center", wrap_text=True)
            for i, col in enumerate(df.columns, 1):
                letter = get_column_letter(i)
                if col in WIDE:
                    width = WIDE[col]
                else:
                    sample = [len(str(v)) for v in df[col].head(500) if v is not None and v == v]
                    width = min(max([len(col)] + sample) + 2, 30)
                ws.column_dimensions[letter].width = width
                fmt = ("0.00" if col in PRICE_COLS else
                       "yyyy-mm-dd hh:mm" if col.startswith("Jam") else
                       "yyyy-mm-dd" if col == "Tanggal" else
                       "#,##0.00;[Red]-#,##0.00" if "USD" in col else
                       "0.0;[Red]-0.0" if col in ("Pips", "R") else None)
                for (cell,) in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                    if fmt:
                        cell.number_format = fmt
                    if col in WIDE:
                        cell.alignment = Alignment(wrap_text=True, vertical="top")
                    elif col == "Keputusan" and cell.value in FILL:
                        cell.fill = PatternFill("solid", fgColor=FILL[cell.value])
                        cell.font = Font(bold=True)
            if name == "Ringkasan Harian" and ws.max_row > 1:
                for c in ws[ws.max_row]:
                    c.font = Font(bold=True)
    return buf.getvalue()


def export(start: date | None = None, end: date | None = None, mode: str | None = None,
           include_new: bool = False) -> tuple[bytes, str]:
    """(isi .xlsx, nama file) — dipakai CLI dan dashboard."""
    con = connect()
    try:
        frames = build_frames(con, start, end, mode, include_new)
    finally:
        con.close()
    span = f"{start or 'awal'}_{end or 'sekarang'}"
    return to_xlsx(frames), f"jurnal_tg_{span}{'_' + mode if mode else ''}.xlsx"


def main() -> None:
    ap = argparse.ArgumentParser(description="Ekspor jurnal trading sinyal Telegram ke .xlsx")
    ap.add_argument("--from", dest="start", type=date.fromisoformat, help="tanggal awal WIB (YYYY-MM-DD)")
    ap.add_argument("--to", dest="end", type=date.fromisoformat, help="tanggal akhir WIB (YYYY-MM-DD)")
    ap.add_argument("--mode", choices=["DEMO", "LOG"], help="hanya trade mode ini")
    ap.add_argument("--all", action="store_true", help="ikutkan sinyal yang belum diproses runner (status NEW)")
    ap.add_argument("--out", type=Path, help="file keluaran (default data/<nama otomatis>)")
    a = ap.parse_args()
    data, name = export(a.start, a.end, a.mode, a.all)
    out = a.out or settings.DATA_DIR / name
    out.write_bytes(data)
    print(f"jurnal tersimpan: {out}")


if __name__ == "__main__":
    main()
