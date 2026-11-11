from datetime import date

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
