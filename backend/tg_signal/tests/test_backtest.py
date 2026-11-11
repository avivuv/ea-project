"""Uji simulasi backtest dengan bar sintetis (spread 0 supaya angka mudah dicek)."""
from datetime import datetime, timezone

import pandas as pd

from tg_signal.backtest_tg import Bars, Signal, Variant, simulate
from tg_signal.confirmation import confirmed

T0 = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)


def make_bars(closes: list[float], lows: list[float] | None = None, highs: list[float] | None = None,
              opens: list[float] | None = None) -> Bars:
    n = len(closes)
    idx = pd.date_range(T0, periods=n, freq="1min", tz="UTC")
    df = pd.DataFrame({
        "open": opens or closes,
        "high": highs or [c + 0.05 for c in closes],
        "low": lows or [c - 0.05 for c in closes],
        "close": closes,
        "spread": [0.0] * n,
    }, index=idx)
    return Bars(df)


def sig(direction="BUY", a=62, b=58) -> Signal:
    # pesan diterima di detik ke-30 menit pertama → simulasi mulai bar ke-1, ref = open bar ke-0
    return Signal(T0.replace(second=30), direction, a, b, 30, 1)


def test_limit_zero_hits_tp():
    # ref 4165 → zona 4162/4158; turun ke 4162 lalu naik 1.0 (10 pips)
    bars = make_bars([4165, 4164, 4162.0, 4162.5, 4163.2])
    r = simulate(sig(), Variant("ZERO", 1, 10), bars)
    assert (r["outcome"], r["pips"], r["zero"], r["last"]) == ("TP", 10, 4162, 4158)


def test_limit_zero_sl_from_entry_vs_zone():
    # turun dari 4162 ke 4158.9 (−3.1) lalu balik ke 4163.5
    closes = [4165, 4164, 4162.0, 4160.0, 4158.9, 4160.0, 4163.5]
    bars = make_bars(closes)
    r_entry = simulate(sig(), Variant("ZERO", 1, 10, "entry"), bars)
    assert (r_entry["outcome"], r_entry["pips"]) == ("SL", -30)
    r_zone = simulate(sig(), Variant("ZERO", 1, 10, "zone"), bars)   # SL di 4155 → selamat
    assert r_zone["outcome"] == "TP"


def test_limit_mid_expires_when_provider_tp_reached_first():
    # sentuh zero 4162, naik ke 4163.1 (zero + 10 pips) tanpa pernah ke mid 4160
    bars = make_bars([4165, 4164, 4162.0, 4162.6, 4163.1])
    r = simulate(sig(), Variant("MID", 1, 10), bars)
    assert r["outcome"] == "EXPIRED_TP"


def test_sell_mirror():
    # SELL 42-46, ref 4140 → zero 4142, last 4146; naik ke 4142 lalu turun 1.0
    bars = make_bars([4140, 4141, 4142.0, 4141.5, 4140.9])
    r = simulate(sig("SELL", 42, 46), Variant("ZERO", 1, 10), bars)
    assert (r["outcome"], r["pips"], r["zero"]) == ("TP", 10, 4142)


def test_confirmation_patterns_buy():
    o = [10.0, 9.0, 9.2, 9.5]
    h = [10.1, 9.1, 9.9, 9.9]
    l = [9.0, 8.9, 9.1, 9.3]
    c = [9.1, 9.0, 9.8, 9.8]
    # bar 3: low 9.3 > high bar 1 (9.1) → FVG bullish; zona zero 9.0
    assert confirmed("FVG", "BUY", o, h, l, c, 3, zero=9.0)
    # OB di bar 2 butuh bar 1 bearish; bar 1 doji (close == open) → bukan OB
    assert not confirmed("OB", "BUY", o, h, l, c, 2, zero=9.0)
    # di luar zona (zero jauh di bawah) → tidak valid
    assert not confirmed("FVG", "BUY", o, h, l, c, 3, zero=5.0)


def test_confirmation_ob_buy():
    o = [10.0, 9.8, 9.3]
    h = [10.1, 9.85, 10.0]
    l = [9.7, 9.2, 9.25]
    c = [9.8, 9.3, 9.95]     # bar1 bearish, bar2 bullish close 9.95 > high bar1 9.85
    assert confirmed("OB", "BUY", o, h, l, c, 2, zero=9.3)
