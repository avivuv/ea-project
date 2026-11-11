from datetime import date
import pytest

from tg_signal.parser import classify, parse_report, parse_signal
from tg_signal.tests.samples import REPORT_11_11_2026, SIGNAL_BUY_62_58


def test_parse_real_signal():
    s = parse_signal(SIGNAL_BUY_62_58)
    assert s is not None
    assert (s.direction, s.level_first, s.level_last) == ("BUY", 62, 58)
    assert s.sl_pips == 30 and s.sl_from_message


def test_signal_variants():
    s = parse_signal("sell 42 - 46\nSL: 25 pip")
    assert (s.direction, s.level_first, s.level_last, s.sl_pips) == ("SELL", 42, 46, 25)
    s = parse_signal("BUY 02–98")            # en dash
    assert (s.level_first, s.level_last) == (2, 98)


def test_signal_default_sl():
    s = parse_signal("BUY 62-58\nEntry tunggu konfirmasi", default_sl_pips=30)
    assert s.sl_pips == 30 and not s.sl_from_message


def test_non_signal():
    assert parse_signal("Cek Pesan yg di-PIN ya gaesss... DYOR") is None
    assert parse_signal("") is None
    assert parse_signal("Hari ini BUY 62-58 sudah TP") is None   # bukan di awal baris


def test_report_is_not_signal():
    assert parse_signal(REPORT_11_11_2026) is None


def test_parse_real_report():
    r = parse_report(REPORT_11_11_2026)
    assert r is not None
    assert r.report_date == date(2026, 11, 11)
    assert len(r.lines) == 20
    first, sixth, last = r.lines[0], r.lines[5], r.lines[19]
    assert (first.no, first.direction, first.level_first, first.level_last) == (1, "SELL", 42, 46)
    assert (first.win, first.depth, first.outcome) == (True, "ZERO", "TP")
    assert (sixth.win, sixth.depth, sixth.outcome) == (False, "LAST", "SL")
    assert (last.no, last.depth) == (20, "MID")
    assert sum(1 for ln in r.lines if ln.win) == 19


def test_classify():
    assert classify(SIGNAL_BUY_62_58) == "SIGNAL"
    assert classify(REPORT_11_11_2026) == "REPORT"
    assert classify("Selamat pagi semua") == "OTHER"




@pytest.mark.parametrize("text, direction, a, b", [
    ("GOLD BUY 62-58", "BUY", 62, 58),
    ("GOL BUY 62-58\n\nEntry tunggu konfirmasi", "BUY", 62, 58),
    ("SELL ZONE 60-64", "SELL", 60, 64),
    ("GOLD BUY ZONE 62-58", "BUY", 62, 58),
    ("BUY GOLD 72-68", "BUY", 72, 68),
    ("BUY GOLD ZONE 72-68", "BUY", 72, 68),
    ("XAUUSD BUY 4162-4158", "BUY", 4162, 4158),
    ("BUY XAUUSD ZONE 62-58", "BUY", 62, 58),
    ("SELL XAU 42-46", "SELL", 42, 46),
    ("SELL NOW 62-66", "SELL", 62, 66),
    ("SELL LAGI 62-66", "SELL", 62, 66),
    ("BOLEH BUY LAGI 62-58", "BUY", 62, 58),
    ("BBUY 62-58", "BUY", 62, 58),
    ("BBBUY 62-58", "BUY", 62, 58),
    ("SELLL 42-46", "SELL", 42, 46),
    ("SELLN 42-46", "SELL", 42, 46),
])
def test_signal_format_variants(text, direction, a, b):
    s = parse_signal(text)
    assert s is not None, text
    assert (s.direction, s.level_first, s.level_last) == (direction, a, b)
    assert s.flags == []


def test_signal_three_digit_typo():
    s = parse_signal("SELL 62-666")
    assert (s.level_first, s.level_last, s.flags) == (62, 66, ["LEVEL_TYPO"])


@pytest.mark.parametrize("text", ["BUY NOW", "GOLD SELL NOW", "TP", "MID", "Yg buy limit 3324 masih berlaku min?"])
def test_short_admin_updates_are_not_signals(text):
    assert parse_signal(text) is None


def test_report_variants():
    text = ("Report Jum'at (28-11-2025):\n"
            "1. SELL 68-72 ✅ MID - TP\n"
            "2. BUY 62 ✅ ZERO-TP\n"
            "3. BUY 55-51 ✅ ZERO -TP\n"
            "4. SELL 40-44 ❌ LAST-SL")
    r = parse_report(text)
    assert r.report_date == date(2025, 11, 28)
    assert [(ln.no, ln.level_last, ln.depth, ln.outcome) for ln in r.lines] == [
        (1, 72, "MID", "TP"), (2, None, "ZERO", "TP"), (3, 51, "ZERO", "TP"), (4, 44, "LAST", "SL")]
    assert parse_signal(text) is None


def test_report_single_digit_date():
    r = parse_report("Report Selasa (13-1-2026)\n1. BUY 62-58 ✅ ZERO-TP")
    assert r.report_date == date(2026, 1, 13)
