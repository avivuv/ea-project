"""Auto-reconnect MT5 (mt5_conn.ensure) dengan modul MetaTrader5 tiruan."""
from types import SimpleNamespace

import pytest

from tg_signal import mt5_conn

DEMO, REAL = 0, 2


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = DEMO

    def __init__(self, up=True, trade_mode=DEMO, init_ok=True):
        self.up, self.trade_mode, self.init_ok = up, trade_mode, init_ok
        self.calls = []

    def terminal_info(self):
        return SimpleNamespace(connected=True) if self.up else None

    def account_info(self):
        return SimpleNamespace(login=1, server="Demo", trade_mode=self.trade_mode) if self.up else None

    def last_error(self):
        return (1, "Success") if self.up else (-10001, "IPC send failed")

    def shutdown(self):
        self.calls.append("shutdown")

    def initialize(self, **kw):
        self.calls.append("initialize")
        if self.init_ok:
            self.up = True
        return self.init_ok

    def symbol_select(self, s, on):
        self.calls.append(f"select {s}")
        return True


@pytest.fixture
def fake(monkeypatch):
    def make(**kw):
        f = FakeMT5(**kw)
        monkeypatch.setattr(mt5_conn, "mt5", f)
        return f
    return make


def test_sehat_tidak_reconnect(fake):
    f = fake(up=True)
    assert mt5_conn.ensure(["XAUUSD"]) is None
    assert f.calls == []


def test_putus_lalu_pulih(fake):
    f = fake(up=False)
    msg = mt5_conn.ensure(["XAUUSD"])
    assert "pulih" in msg and "-10001" in msg
    assert f.calls == ["shutdown", "initialize", "select XAUUSD"]


def test_terminal_belum_siap_raise(fake):
    fake(up=False, init_ok=False)
    with pytest.raises(RuntimeError, match="initialize gagal"):
        mt5_conn.ensure(["XAUUSD"])


def test_reconnect_ke_akun_real_ditolak(fake):
    f = fake(up=False, trade_mode=REAL)
    with pytest.raises(RuntimeError, match="bukan akun DEMO"):
        mt5_conn.ensure(["XAUUSD"])
    assert f.calls[-1] == "shutdown"
