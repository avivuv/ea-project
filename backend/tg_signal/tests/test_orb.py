import numpy as np
import pandas as pd

from tg_signal import orb


def _bars(start, n, freq, closes, spread=0.0):
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    c = np.asarray(closes, float)
    return pd.DataFrame({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "spread": spread}, index=idx)


def test_session_open_dst():
    assert orb.session_open_utc("2026-08-03").strftime("%H:%M") == "13:30"     # EDT
    assert orb.session_open_utc("2026-11-16").strftime("%H:%M") == "14:30"     # EST
    assert orb.session_open_utc("2026-11-16").tz_convert("Asia/Jakarta").strftime("%H:%M") == "21:30"


def test_find_breakout_buy_first_close_above_range():
    op = orb.session_open_utc("2026-11-16")
    m1 = _bars(op, 15, "1min", [100.0] * 15)                                    # range 99.5–100.5
    m5 = _bars(op, 9, "5min", [100, 100, 100, 100.2, 101.0, 99.0, 102, 103, 104])
    sig = orb.find_breakout(m1, m5, op)
    assert (sig["or_hi"], sig["or_lo"]) == (100.5, 99.5)
    assert sig["dir"] == "BUY" and sig["bar"] == op + pd.Timedelta(minutes=20)
    assert sig["close_time"] == op + pd.Timedelta(minutes=25)


def test_find_breakout_incomplete_range_and_no_break():
    op = orb.session_open_utc("2026-11-16")
    assert orb.find_breakout(_bars(op, 10, "1min", [100] * 10), _bars(op, 2, "5min", [100, 100]), op) is None
    sig = orb.find_breakout(_bars(op, 15, "1min", [100] * 15), _bars(op, 6, "5min", [100] * 6), op)
    assert "dir" not in sig


def test_plan_order_sl_opposite_side_tp_2r():
    sig = {"dir": "SELL", "or_hi": 110.0, "or_lo": 100.0}
    sl, tp, risk = orb.plan_order(sig, 99.0)
    assert sl == 110.1 and round(risk, 2) == 11.1 and round(tp, 2) == round(99.0 - 2 * 11.1, 2)
    assert orb.plan_order({"dir": "BUY", "or_hi": 100.3, "or_lo": 100.0}, 100.4) is None    # risiko < $1


def test_bias_uses_only_closed_h1_bar():
    h1 = _bars("2026-01-01", 120, "60min", np.linspace(100, 160, 120))
    b = orb.h1_bias(h1)
    last_open = h1.index[-1]
    assert orb.bias_at(b, last_open + pd.Timedelta(minutes=60), True)
    assert not orb.bias_at(b, last_open + pd.Timedelta(minutes=60), False)


def test_entry_extension_ratio_outside_range():
    sig = {"dir": "SELL", "or_hi": 3473.51, "or_lo": 3454.81}
    assert abs(orb.entry_extension(sig, 3430.59) - 1.295) < 0.01        # kasus live 25 Nov 2026 → dilewati
    assert orb.entry_extension(sig, 3457.0) == 0.0                     # masih di dalam range
    buy = {"dir": "BUY", "or_hi": 110.0, "or_lo": 100.0}
    assert orb.entry_extension(buy, 115.0) == 0.5


def test_near_news_window_both_sides():
    news = [pd.Timestamp("2026-11-25 13:30", tz="UTC")]                # 08:30 ET
    entry = pd.Timestamp("2026-11-25 15:20", tz="UTC")                 # 110 mnt setelah news
    assert orb.near_news(entry, news, 120) == news[0]
    assert orb.near_news(entry, news, 60) is None
    assert orb.near_news(pd.Timestamp("2026-11-25 11:40", tz="UTC"), news, 120) == news[0]   # sebelum news
    assert orb.near_news(entry, [], 120) is None
