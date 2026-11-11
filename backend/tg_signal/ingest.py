"""
Memproses satu pesan Telegram → simpan ke Store sesuai jenisnya.
Dipakai oleh tg_client (dump riwayat & live). Tidak import telethon.

    python -m tg_signal.ingest --stats     # ringkasan isi database
"""
from __future__ import annotations

import argparse
from datetime import datetime

from tg_signal import parser
from tg_signal.store import Store


def ingest_message(store: Store, chat_id: int, msg_id: int, date: datetime,
                   text: str, edit_date: datetime | None = None,
                   default_sl_pips: float = 30, sender_id: int | None = None,
                   sender_name: str | None = None) -> str:
    """Return kind pesan: SIGNAL | REPORT | OTHER | EMPTY | UNCHANGED."""
    text = (text or "").strip()
    if not text:
        return "EMPTY"

    report = parser.parse_report(text)
    signal = None if report else parser.parse_signal(text, default_sl_pips)
    kind = "REPORT" if report else "SIGNAL" if signal else "OTHER"

    message_id, changed = store.upsert_message(chat_id, msg_id, date, text, kind, edit_date,
                                               sender_id, sender_name)
    if not changed:
        return "UNCHANGED"

    _save_parsed(store, message_id, date, report, signal)
    return kind


def _save_parsed(store: Store, message_id: int, date: datetime, report, signal) -> None:
    if report:
        store.replace_report_lines(message_id, report.report_date.isoformat(), report.lines)
    elif signal:
        store.upsert_signal(message_id, date, signal.direction, signal.level_first,
                            signal.level_last, signal.sl_pips, signal.flags)


def reparse_all(store: Store, default_sl_pips: float = 30) -> dict[str, int]:
    """Parse ulang semua pesan tersimpan (setelah parser diubah) tanpa dump ulang Telegram."""
    store.reset_derived()
    counts: dict[str, int] = {}
    for row in store.all_messages():
        text = row["text"]
        report = parser.parse_report(text)
        signal = None if report else parser.parse_signal(text, default_sl_pips)
        kind = "REPORT" if report else "SIGNAL" if signal else "OTHER"
        store.set_kind(row["id"], kind)
        _save_parsed(store, row["id"], datetime.fromisoformat(row["date_utc"]), report, signal)
        counts[kind] = counts.get(kind, 0) + 1
    store.conn.commit()
    return counts


def _print_stats(store: Store, show_suspect: int) -> None:
    c = store.counts()
    total = sum(v for k, v in c.items() if k != "report_lines")
    print(f"Total pesan   : {total}")
    for k in ("SIGNAL", "REPORT", "OTHER"):
        print(f"  {k:<11}: {c.get(k, 0)}")
    print(f"Baris laporan : {c['report_lines']}")

    suspect = store.suspect_other_messages()
    print(f"\nPesan OTHER yang menyebut BUY/SELL (kandidat gagal parse): {len(suspect)}")
    for row in suspect[:show_suspect]:
        first_line = row["text"].splitlines()[0][:80]
        print(f"  [{row['date_utc']}] #{row['msg_id']}: {first_line}")


def main() -> None:
    from tg_signal import settings

    ap = argparse.ArgumentParser(description="Statistik database tg_signal")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--reparse", action="store_true", help="parse ulang semua pesan di database")
    ap.add_argument("--show", type=int, default=20, help="jumlah kandidat gagal parse yang ditampilkan")
    args = ap.parse_args()
    store = Store(settings.DB_PATH)
    try:
        if args.reparse:
            print("Reparse:", reparse_all(store, settings.TG_DEFAULT_SL_PIPS))
        _print_stats(store, args.show)
    finally:
        store.close()


if __name__ == "__main__":
    main()
