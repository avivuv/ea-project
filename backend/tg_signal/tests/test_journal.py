"""Jurnal trading .xlsx: keputusan, alasan, hasil trade, ringkasan."""
import io
from datetime import datetime, timedelta, timezone

import pandas as pd

from tg_signal import journal
from tg_signal.ingest import ingest_message
from tg_signal.store import Store

T0 = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)     # 10:00 WIB


def make_store(tmp_path):
    st = Store()
    ingest_message(st, 1, 10, T0, "BUY 89-85")
    ingest_message(st, 1, 11, T0 + timedelta(minutes=30), "SELL 12-16")
    ingest_message(st, 1, 12, T0 + timedelta(minutes=40), "BUY 70-66")
    s_entry, s_skip, s_new = (st.signal_for_message(1, m)["id"] for m in (10, 11, 12))
    st.set_zone(s_entry, 3887.0, 3889.0, 3885.0, [])
    st.set_status(s_entry, "PENDING", "paper @ 3888.00", ts=T0)
    st.set_status(s_entry, "OPEN", "paper", ts=T0 + timedelta(minutes=5))
    tid = st.add_trade(s_entry, "LOG", None, "BUY", 0.01, T0 + timedelta(minutes=5), 3888.0, 3885.0, 3891.0)
    st.close_trade(tid, T0 + timedelta(minutes=25), 3891.0, 0.3, 30.0, "TP")
    st.set_status(s_entry, "CLOSED", "TP", ts=T0 + timedelta(minutes=25))
    st.set_status(s_skip, "REJECTED", "ZONE_TOO_FAR", ts=T0 + timedelta(minutes=30))
    log = tmp_path / "live.log"
    log.write_text("2026-11-16 10:00:00,000 INFO sinyal #10 BUY 89-85 → zona 3889/3885 | POI di zona: FVG 3887.0-3888.0"
                   "\n2026-11-16 10:00:00,100 INFO sinyal #10 BUY 89-85 → zona 3889/3885 | POI FVG 3887.0-3888.0 | "
                   "LOG BUY LIMIT @ 3888.00\n", encoding="utf-8")
    return st, log


def test_frames_decision_and_reason(tmp_path):
    st, log = make_store(tmp_path)
    fr = journal.build_frames(st.conn, log_path=log)
    j = fr["Jurnal"]
    assert list(j["Keputusan"]) == ["ENTRY", "SKIP"]          # sinyal NEW tidak ikut secara default
    e, s = j.iloc[0], j.iloc[1]
    assert e["Alasan entry / skip"] == "Limit terisi — POI FVG 3887.0-3888.0"
    assert e["POI terdeteksi di zona"] == "FVG 3887.0-3888.0"
    assert (e["Hasil"], e["Pips"], e["R"]) == ("TP", 30.0, 1.0)
    assert s["Alasan entry / skip"] == "Zona terlalu jauh dari harga saat sinyal masuk"
    d = fr["Ringkasan Harian"].iloc[0]
    assert (d["Sinyal"], d["Entry"], d["Skip"], d["Win"]) == (2, 1, 1, 1)
    assert len(journal.build_frames(st.conn, include_new=True, log_path=log)["Jurnal"]) == 3
    assert journal.build_frames(st.conn, mode="DEMO", log_path=log)["Trades"].empty


def test_date_filter_and_xlsx(tmp_path):
    st, log = make_store(tmp_path)
    fr = journal.build_frames(st.conn, start=T0.date() + timedelta(days=1), log_path=log)
    assert fr["Jurnal"].empty
    data = journal.to_xlsx(journal.build_frames(st.conn, log_path=log))
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
    assert list(sheets) == ["Jurnal", "Trades", "Ringkasan Harian", "Alasan Skip"]
    assert len(sheets["Trades"]) == 1


def test_skip_category():
    assert journal.skip_category("admin sudah TP (pesan admin 'TP' → BUY 66-62)") == "Admin sudah TP sebelum entry"
    assert journal.human_reason("ORDER_FAILED: retcode 10006") == "Order ditolak MT5: retcode 10006"
