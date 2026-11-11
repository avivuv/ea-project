"""
Penyimpanan SQLite: pesan mentah, sinyal, laporan, event status.
Waktu selalu disimpan sebagai ISO-8601 UTC.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    chat_id     INTEGER NOT NULL,
    msg_id      INTEGER NOT NULL,
    sender_id   INTEGER,
    sender_name TEXT,
    date_utc    TEXT    NOT NULL,
    edit_utc    TEXT,
    text        TEXT    NOT NULL,
    kind        TEXT    NOT NULL,              -- SIGNAL | REPORT | OTHER
    UNIQUE (chat_id, msg_id)
);

CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY,
    message_id      INTEGER NOT NULL UNIQUE REFERENCES messages(id),
    received_utc    TEXT    NOT NULL,
    direction       TEXT    NOT NULL,
    level_first     INTEGER NOT NULL,
    level_last      INTEGER NOT NULL,
    sl_pips         REAL    NOT NULL,
    -- diisi saat zona di-resolve (butuh harga referensi)
    ref_price       REAL,
    zero            REAL,
    last            REAL,
    flags           TEXT    NOT NULL DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'NEW',
    status_reason   TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS signal_events (
    id          INTEGER PRIMARY KEY,
    signal_id   INTEGER NOT NULL REFERENCES signals(id),
    ts_utc      TEXT    NOT NULL,
    from_status TEXT    NOT NULL,
    to_status   TEXT    NOT NULL,
    reason      TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS report_lines (
    id          INTEGER PRIMARY KEY,
    message_id  INTEGER NOT NULL REFERENCES messages(id),
    report_date TEXT    NOT NULL,
    seq         INTEGER NOT NULL,              -- urutan baris di pesan (nomor bisa dobel)
    no          INTEGER NOT NULL,
    direction   TEXT    NOT NULL,
    level_first INTEGER NOT NULL,
    level_last  INTEGER NOT NULL,
    win         INTEGER,
    depth       TEXT    NOT NULL,
    outcome     TEXT    NOT NULL,
    UNIQUE (message_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_report_date ON report_lines(report_date);
"""


def utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ── messages ────────────────────────────────────────────────────────────
    def upsert_message(self, chat_id: int, msg_id: int, date: datetime,
                       text: str, kind: str, edit_date: datetime | None = None,
                       sender_id: int | None = None, sender_name: str | None = None) -> tuple[int, bool]:
        """Return (message_row_id, changed). changed=False bila teks identik sudah ada."""
        row = self.conn.execute(
            "SELECT id, text FROM messages WHERE chat_id=? AND msg_id=?", (chat_id, msg_id)
        ).fetchone()
        if row and row["text"] == text:
            return row["id"], False
        edit_iso = utc_iso(edit_date) if edit_date else None
        if row:
            self.conn.execute(
                "UPDATE messages SET text=?, kind=?, edit_utc=? WHERE id=?",
                (text, kind, edit_iso, row["id"]),
            )
            self.conn.commit()
            return row["id"], True
        cur = self.conn.execute(
            """INSERT INTO messages (chat_id, msg_id, sender_id, sender_name, date_utc, edit_utc, text, kind)
               VALUES (?,?,?,?,?,?,?,?)""",
            (chat_id, msg_id, sender_id, sender_name, utc_iso(date), edit_iso, text, kind),
        )
        self.conn.commit()
        return cur.lastrowid, True

    def max_msg_id(self, chat_id: int) -> int:
        row = self.conn.execute("SELECT MAX(msg_id) FROM messages WHERE chat_id=?", (chat_id,)).fetchone()
        return row[0] or 0

    # ── signals ─────────────────────────────────────────────────────────────
    def upsert_signal(self, message_id: int, received: datetime, direction: str,
                      level_first: int, level_last: int, sl_pips: float) -> int:
        """Sinyal baru, atau update bila pesan diedit dan status masih NEW/WAITING."""
        row = self.conn.execute(
            "SELECT id, status FROM signals WHERE message_id=?", (message_id,)
        ).fetchone()
        if row is None:
            cur = self.conn.execute(
                """INSERT INTO signals (message_id, received_utc, direction, level_first, level_last, sl_pips)
                   VALUES (?,?,?,?,?,?)""",
                (message_id, utc_iso(received), direction, level_first, level_last, sl_pips),
            )
            self.conn.commit()
            return cur.lastrowid
        if row["status"] in ("NEW", "WAITING"):
            self.conn.execute(
                """UPDATE signals SET direction=?, level_first=?, level_last=?, sl_pips=?,
                   ref_price=NULL, zero=NULL, last=NULL, flags='', status='NEW', status_reason='edited'
                   WHERE id=?""",
                (direction, level_first, level_last, sl_pips, row["id"]),
            )
            self.conn.commit()
        return row["id"]

    def set_status(self, signal_id: int, to_status: str, reason: str = "",
                   ts: datetime | None = None) -> None:
        row = self.conn.execute("SELECT status FROM signals WHERE id=?", (signal_id,)).fetchone()
        if row is None:
            raise KeyError(signal_id)
        ts_iso = utc_iso(ts or datetime.now(timezone.utc))
        self.conn.execute(
            "UPDATE signals SET status=?, status_reason=? WHERE id=?", (to_status, reason, signal_id)
        )
        self.conn.execute(
            "INSERT INTO signal_events (signal_id, ts_utc, from_status, to_status, reason) VALUES (?,?,?,?,?)",
            (signal_id, ts_iso, row["status"], to_status, reason),
        )
        self.conn.commit()

    def signals(self, status: str | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM signals" + (" WHERE status=?" if status else "") + " ORDER BY received_utc"
        return self.conn.execute(q, (status,) if status else ()).fetchall()

    # ── reports ─────────────────────────────────────────────────────────────
    def replace_report_lines(self, message_id: int, report_date: str, lines: list) -> None:
        self.conn.execute("DELETE FROM report_lines WHERE message_id=?", (message_id,))
        self.conn.executemany(
            """INSERT INTO report_lines (message_id, report_date, seq, no, direction, level_first,
               level_last, win, depth, outcome) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [(message_id, report_date, seq, ln.no, ln.direction, ln.level_first, ln.level_last,
              None if ln.win is None else int(ln.win), ln.depth, ln.outcome) for seq, ln in enumerate(lines, 1)],
        )
        self.conn.commit()

    # ── statistik ───────────────────────────────────────────────────────────
    def counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT kind, COUNT(*) n FROM messages GROUP BY kind").fetchall()
        out = {r["kind"]: r["n"] for r in rows}
        out["report_lines"] = self.conn.execute("SELECT COUNT(*) FROM report_lines").fetchone()[0]
        return out

    def suspect_other_messages(self) -> list[sqlite3.Row]:
        """Pesan OTHER yang menyebut BUY/SELL — kandidat gagal parse."""
        return self.conn.execute(
            """SELECT * FROM messages WHERE kind='OTHER'
               AND (text LIKE '%BUY%' OR text LIKE '%SELL%' OR text LIKE '%buy%' OR text LIKE '%sell%')
               ORDER BY date_utc"""
        ).fetchall()
