from datetime import datetime, timezone

from tg_signal import run_live, settings
from tg_signal.executor import Tick


class FakeStore:
    def __init__(self, zero):
        self.zero, self.tp_set, self.closed = zero, None, None

    def signal_zero(self, sid):
        return self.zero

    def set_trade_tp(self, tid, tp):
        self.tp_set = tp

    def close_trade(self, tid, when, exit_price, profit, pips, reason):
        self.closed = (exit_price, reason)

    def set_status(self, *a):
        pass

    def day_stats(self, *a):
        return 0, 0.0


class FakeEx:
    def __init__(self, bid):
        self.bid = bid

    def tick(self):
        return Tick(self.bid, self.bid + 0.2, datetime.now(timezone.utc))


def trade(entry=3887.5, tp=3890.5):
    return {"id": 1, "signal_id": 7, "ticket": None, "direction": "BUY", "entry": entry, "sl": entry - 3,
            "tp": tp, "lot": 0.01}


def make(bid, zero=3889.0):
    tr = run_live.LiveTrader(FakeStore(zero), FakeEx(bid), "LOG")
    return tr


def test_admin_tp_not_reached_keeps_tp():
    tr = make(bid=3889.5)                       # ZERO + 10 pips = 3890.0 belum
    tr._admin_tp([trade()])
    assert tr.store.tp_set is None and tr.store.closed is None


def test_admin_tp_reached_lowers_tp_to_20():
    tr = make(bid=3890.2, zero=3888.5)          # admin TP 3889.5 tercapai; entry+20 = 3889.5? pakai entry lebih rendah
    tr._admin_tp([trade(entry=3886.5, tp=3889.5)])   # TP awal +30 = 3889.5, level baru +20 = 3888.5 → harga sudah lewat
    assert tr.store.closed is not None and tr.store.closed[1] == "TP_ADMIN"


def test_admin_tp_reached_below_new_tp_modifies():
    tr = make(bid=3890.0, zero=3889.0)          # admin TP 3890.0 tercapai
    tr._admin_tp([trade(entry=3888.5, tp=3891.5)])   # level baru 3890.5 > harga → ubah TP
    assert round(tr.store.tp_set, 2) == 3890.5 and tr.store.closed is None


def test_admin_tp_already_lowered_skips():
    tr = make(bid=3890.2, zero=3889.0)
    tr._admin_tp([trade(entry=3888.5, tp=3890.5)])
    assert tr.store.tp_set is None and tr.store.closed is None
