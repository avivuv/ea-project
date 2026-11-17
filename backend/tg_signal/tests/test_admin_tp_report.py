"""Admin TP dipicu baris baru di pesan Report admin."""
from datetime import datetime, timedelta, timezone

from tg_signal import run_live
from tg_signal.executor import Tick
from tg_signal.ingest import ingest_message
from tg_signal.parser import parse_report
from tg_signal.store import Store

T0 = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)


class FakeEx:
    def __init__(self, bid):
        self.bid = bid

    def tick(self):
        return Tick(self.bid, self.bid + 0.2, datetime.now(timezone.utc))


def setup(bid=3888.0):
    st = Store()
    tr = run_live.LiveTrader(st, FakeEx(bid), "LOG")
    return st, tr


def open_trade(st, msg_id, text, when, entry=3886.5):
    ingest_message(st, 1, msg_id, when, text)
    sig = st.signal_for_message(1, msg_id)
    return st.add_trade(sig["id"], "LOG", None, sig["direction"], 0.01, when, entry, entry - 3, entry + 3)


def tp_of(st, tid):
    return st.conn.execute("SELECT tp, outcome FROM trades WHERE id=?", (tid,)).fetchone()


def test_new_tp_line_lowers_tp():
    st, tr = setup(bid=3888.0)                      # entry 3886.5 + 20 pips = 3888.5 > harga → ubah TP
    tid = open_trade(st, 10, "BUY 89-85", T0)
    rep = parse_report("Report Senin (16-11-2026)\n1. BUY 89-85 ✅ ZERO-TP")
    tr.handle_report(rep, 0, T0 + timedelta(minutes=20))
    assert round(tp_of(st, tid)["tp"], 2) == 3888.5


def test_tp_line_past_new_tp_closes():
    st, tr = setup(bid=3889.0)                      # harga sudah lewat 3888.5 → tutup
    tid = open_trade(st, 10, "BUY 89-85", T0)
    rep = parse_report("Report Senin (16-11-2026)\n1. BUY 89-85 ✅ ZERO-TP")
    tr.handle_report(rep, 0, T0 + timedelta(minutes=20))
    assert tp_of(st, tid)["outcome"] == "TP_ADMIN"


def test_only_new_lines_used_and_older_same_level_untouched():
    st, tr = setup(bid=3888.0)
    old = open_trade(st, 10, "SELL 45-49", T0)       # baris 1 milik sinyal lama ini
    t_new = T0 + timedelta(hours=1)
    ingest_message(st, 1, 11, t_new, "BUY 30-26")
    new = open_trade(st, 12, "SELL 45-49", t_new + timedelta(minutes=10), entry=3890.0)
    text = "Report Senin (16-11-2026)\n1. SELL 45-49 ✅ ZERO-TP\n2. BUY 30-26 ✅ ZERO-TP"
    ingest_message(st, 1, 20, t_new, text)
    rep = parse_report(text)
    tr.handle_report(rep, 2, t_new + timedelta(minutes=30))   # tidak ada baris baru
    assert tp_of(st, new)["tp"] == 3893.0 and tp_of(st, old)["tp"] == 3889.5


def test_sl_line_ignored():
    st, tr = setup(bid=3888.0)
    tid = open_trade(st, 10, "BUY 89-85", T0)
    rep = parse_report("Report Senin (16-11-2026)\n1. BUY 89-85 ❌ LAST-SL")
    tr.handle_report(rep, 0, T0 + timedelta(minutes=20))
    assert tp_of(st, tid)["tp"] == 3889.5


def test_duplicate_signals_both_lowered():
    st, tr = setup(bid=3888.0)
    a = open_trade(st, 10, "BUY 89-85", T0)
    b = open_trade(st, 11, "BUY 89-85\nSL 30 pips", T0 + timedelta(minutes=1))
    rep = parse_report("Report Senin (16-11-2026)\n1. BUY 89-85 ✅ ZERO-TP")
    tr.handle_report(rep, 0, T0 + timedelta(minutes=20))
    assert round(tp_of(st, a)["tp"], 2) == round(tp_of(st, b)["tp"], 2) == 3888.5


def test_max_report_lines_counts_latest_cumulative():
    st, _ = setup()
    ingest_message(st, 1, 20, T0, "Report Senin (16-11-2026)\n1. BUY 89-85 ✅ ZERO-TP")
    ingest_message(st, 1, 21, T0, "Report Senin (16-11-2026)\n1. BUY 89-85 ✅ ZERO-TP\n2. SELL 45-49 ✅ MID-TP")
    assert st.max_report_lines("2026-11-16") == 2


def pending_signal(st, msg_id, text, when, zero, price):
    ingest_message(st, 1, msg_id, when, text)
    sig = st.signal_for_message(1, msg_id)
    st.set_zone(sig["id"], zero, zero, zero - 4, [])
    st.set_status(sig["id"], "PENDING", f"paper @ {price:.2f}")
    return sig["id"]


def status_of(st, sid):
    return st.conn.execute("SELECT status FROM signals WHERE id=?", (sid,)).fetchone()[0]


def test_report_tp_expires_unfilled_pending():
    st, tr = setup(bid=3889.5)
    sid = pending_signal(st, 10, "BUY 89-85", T0, zero=3889.0, price=3886.0)
    rep = parse_report("Report Senin (16-11-2026)\n1. BUY 89-85 ✅ ZERO-TP")
    tr.handle_report(rep, 0, T0 + timedelta(minutes=20))
    assert status_of(st, sid) == "EXPIRED"


def test_pending_kept_when_price_passes_tp_without_admin(monkeypatch):
    from tg_signal import settings
    monkeypatch.setattr(settings, "TG_ENTRY_MODE", "ZONE")   # tanpa re-price POI
    st, tr = setup(bid=3893.5)                      # jauh lewat ZERO + 10/30 pips, admin belum bilang TP
    sid = pending_signal(st, 10, "BUY 89-85", T0, zero=3889.0, price=3886.0)
    tr._sync_pendings()
    assert status_of(st, sid) == "PENDING"
    tr.handle_admin_tp_msg(1, "TP", None, T0 + timedelta(minutes=20))
    assert status_of(st, sid) == "EXPIRED"


def test_fill_after_report_tp_gets_lowered_tp():
    st, tr = setup(bid=3887.0)
    sid = pending_signal(st, 10, "BUY 89-85", T0, zero=3889.0, price=3886.0)
    tr._admin_done.add(sid)                         # Report TP masuk, fill belum tercatat
    tr._record_fill({"sid": sid, "direction": "BUY"}, None, 3886.0, 3883.0, 3889.0, T0)
    [t] = st.open_trades("LOG")
    assert round(t["tp"], 2) == 3888.0              # entry + 20 pips


def test_is_admin_tp_patterns():
    from tg_signal.parser import is_admin_tp
    for t in ["TP", "HIT TP", "TP YAA", "DONE TP", "ZERO", "mid", "LAST", "MID TP", "LAST TP",
              "TP DI LAST YAA", "INSTAN", "INSTAN TP", "Instant tp 🔥", "✅ TP"]:
        assert is_admin_tp(t), t
    for t in ["SL", "LAST SL", "BUY NOW", "GOLD SELL NOW", "BUY 62-58", "tpnya nanti ya gaes, sabar dulu",
              "Report Senin (16-11-2026)\n1. BUY 89-85 ✅ ZERO-TP", "Selamat pagi"]:
        assert not is_admin_tp(t), t


def test_short_tp_msg_hits_latest_active_signal():
    st, tr = setup(bid=3888.0)
    old = open_trade(st, 10, "SELL 45-49", T0)
    st.set_status(st.signal_for_message(1, 10)["id"], "OPEN", "paper")
    new = open_trade(st, 11, "BUY 89-85", T0 + timedelta(minutes=30))
    st.set_status(st.signal_for_message(1, 11)["id"], "OPEN", "paper")
    tr.handle_admin_tp_msg(1, "MID TP", None, T0 + timedelta(minutes=40))
    assert round(tp_of(st, new)["tp"], 2) == 3888.5 and tp_of(st, old)["tp"] == 3889.5


def test_short_tp_msg_reply_targets_replied_signal_and_cancels_pending():
    st, tr = setup(bid=3888.0)
    sid = pending_signal(st, 10, "BUY 89-85", T0, zero=3889.0, price=3886.0)
    ingest_message(st, 1, 11, T0 + timedelta(minutes=5), "SELL 45-49")
    st.set_status(st.signal_for_message(1, 11)["id"], "WAITING", "x")
    tr.handle_admin_tp_msg(1, "TP", 10, T0 + timedelta(minutes=20))
    assert status_of(st, sid) == "EXPIRED"
    assert status_of(st, st.signal_for_message(1, 11)["id"]) == "WAITING"
