from datetime import datetime, timezone

from tg_signal.ingest import ingest_message
from tg_signal.store import Store
from tg_signal.tests.samples import REPORT_11_11_2026, SIGNAL_BUY_62_58

T0 = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)


def test_ingest_kinds_and_counts():
    st = Store()
    assert ingest_message(st, 1, 10, T0, SIGNAL_BUY_62_58) == "SIGNAL"
    assert ingest_message(st, 1, 11, T0, REPORT_11_11_2026) == "REPORT"
    assert ingest_message(st, 1, 12, T0, "Selamat pagi, sell nanti ya") == "OTHER"
    assert ingest_message(st, 1, 13, T0, "") == "EMPTY"
    c = st.counts()
    assert (c["SIGNAL"], c["REPORT"], c["OTHER"], c["report_lines"]) == (1, 1, 1, 20)
    assert len(st.suspect_other_messages()) == 1


def test_ingest_same_message_twice_is_unchanged():
    st = Store()
    ingest_message(st, 1, 10, T0, SIGNAL_BUY_62_58)
    assert ingest_message(st, 1, 10, T0, SIGNAL_BUY_62_58) == "UNCHANGED"
    assert len(st.signals()) == 1


def test_edit_updates_signal_while_new():
    st = Store()
    ingest_message(st, 1, 10, T0, "BUY 62-58\nSL 30 pips")
    ingest_message(st, 1, 10, T0, "BUY 64-60\nSL 30 pips", edit_date=T0)
    [sig] = st.signals()
    assert (sig["level_first"], sig["level_last"], sig["status_reason"]) == (64, 60, "edited")


def test_edit_ignored_after_open():
    st = Store()
    ingest_message(st, 1, 10, T0, "BUY 62-58")
    [sig] = st.signals()
    st.set_status(sig["id"], "OPEN", "test")
    ingest_message(st, 1, 10, T0, "BUY 64-60", edit_date=T0)
    [sig] = st.signals()
    assert (sig["level_first"], sig["status"]) == (62, "OPEN")


def test_report_edit_replaces_lines():
    st = Store()
    ingest_message(st, 1, 11, T0, REPORT_11_11_2026)
    shorter = "\n".join(REPORT_11_11_2026.splitlines()[:6])
    ingest_message(st, 1, 11, T0, shorter, edit_date=T0)
    assert st.counts()["report_lines"] == 5
