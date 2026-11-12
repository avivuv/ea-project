"""Alur LiveTrader mode ZONE dengan executor palsu (tanpa MT5/Telegram)."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("telethon")
pytest.importorskip("MetaTrader5")

from tg_signal import run_live, settings  # noqa: E402
from tg_signal.executor import Tick  # noqa: E402
from tg_signal.store import Store  # noqa: E402

CHAT = 1


class FakeEx:
    def __init__(self):
        self.bid, self.ask = 0.0, 0.0
        self.orders: dict[int, dict] = {}
        self.positions: dict[int, SimpleNamespace] = {}
        self.next = 100

    def set(self, bid, spread=0.16):
        self.bid, self.ask = bid, round(bid + spread, 3)

    def tick(self):
        return Tick(self.bid, self.ask, datetime.now(timezone.utc))

    def place_limit(self, direction, lot, price, sl, tp, comment):
        self.next += 1
        self.orders[self.next] = dict(direction=direction, price=price, sl=sl, tp=tp)
        return self.next

    def cancel_order(self, ticket):
        return self.orders.pop(ticket, None) is not None

    def pending_tickets(self):
        return set(self.orders)

    def fill(self, ticket):     # simulasi broker mengisi limit
        o = self.orders.pop(ticket)
        self.positions[ticket] = SimpleNamespace(price_open=o["price"], sl=o["sl"], tp=o["tp"],
                                                 time=int(datetime.now(timezone.utc).timestamp()))

    def position_of(self, ticket):
        return self.positions.get(ticket)

    def entry_deal(self, ticket):
        return None

    def open_market_at(self, direction, lot, sl, tp, comment):
        self.next += 1
        px = self.ask if direction == "BUY" else self.bid
        self.positions[self.next] = SimpleNamespace(price_open=px, sl=sl, tp=tp, time=0)
        return SimpleNamespace(ticket=self.next, price=px, sl=sl, tp=tp, time=datetime.now(timezone.utc))

    def open_tickets(self):
        return set(self.positions)

    def closed_info(self, ticket):
        return None

    def floating_usd(self):
        return getattr(self, "float_usd", 0.0)

    def close_position(self, ticket, comment=""):
        self.positions.pop(ticket, None)
        return True


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "TG_ENTRY_MODE", "ZONE")
    monkeypatch.setattr(settings, "PAUSE_FILE", tmp_path / "PAUSE")
    store, ex = Store(":memory:"), FakeEx()
    return store, ex


def add_signal(store, msg_id, direction, a, b):
    mid, _ = store.upsert_message(CHAT, msg_id, datetime.now(timezone.utc), f"{direction} {a}-{b}", "SIGNAL")
    store.upsert_signal(mid, datetime.now(timezone.utc), direction, a, b, 30)


def status(store, msg_id):
    return store.signal_for_message(CHAT, msg_id)["status"]


def test_demo_above_zone_places_limit_then_fills(env):
    store, ex = env
    tr = run_live.LiveTrader(store, ex, "DEMO")
    ex.set(3974.95)
    add_signal(store, 1, "BUY", 74, 70)
    tr.handle_signal(CHAT, 1)
    assert status(store, 1) == "PENDING"
    (ticket, o), = ex.orders.items()
    assert (o["price"], o["sl"], o["tp"]) == (3974.0, pytest.approx(3967.0), pytest.approx(3977.0))

    tr.sync()                               # belum terisi
    assert status(store, 1) == "PENDING"
    ex.fill(ticket)
    tr.sync()
    assert status(store, 1) == "OPEN"
    t, = store.open_trades("DEMO")
    assert t["ticket"] == ticket and t["entry"] == 3974.0


def test_demo_in_zone_enters_market(env):
    store, ex = env
    tr = run_live.LiveTrader(store, ex, "DEMO")
    ex.set(3972.0)
    add_signal(store, 1, "BUY", 74, 70)
    tr.handle_signal(CHAT, 1)
    assert status(store, 1) == "OPEN"
    assert not ex.orders
    t, = store.open_trades("DEMO")
    assert t["sl"] == pytest.approx(3967.0)


def test_demo_pending_expires_when_tp_reached(env):
    store, ex = env
    tr = run_live.LiveTrader(store, ex, "DEMO")
    ex.set(3982.68)
    add_signal(store, 1, "SELL", 84, 88)
    tr.handle_signal(CHAT, 1)
    assert status(store, 1) == "PENDING"
    ex.set(3980.80)                         # ask ≤ ZERO − 30 pips (3981)
    tr.sync()
    assert status(store, 1) == "EXPIRED"
    assert not ex.orders


def test_new_signal_replaces_pending(env):
    store, ex = env
    tr = run_live.LiveTrader(store, ex, "DEMO")
    ex.set(3982.68)
    add_signal(store, 1, "SELL", 84, 88)
    tr.handle_signal(CHAT, 1)
    add_signal(store, 2, "SELL", 86, 90)
    tr.handle_signal(CHAT, 2)
    assert status(store, 1) == "CANCELLED"
    assert status(store, 2) == "PENDING"
    assert len(ex.orders) == 1


def test_log_mode_paper_pending_fills(env):
    store, ex = env
    tr = run_live.LiveTrader(store, ex, "LOG")
    ex.set(3974.95)
    add_signal(store, 1, "BUY", 74, 70)
    tr.handle_signal(CHAT, 1)
    assert status(store, 1) == "PENDING"
    ex.set(3973.7)                          # ask 3973.86 ≤ 3974
    tr.sync()
    assert status(store, 1) == "OPEN"
    t, = store.open_trades("LOG")
    assert t["entry"] == 3974.0 and t["sl"] == pytest.approx(3967.0)
