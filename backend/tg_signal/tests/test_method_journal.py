"""Jurnal metode non-Telegram: klasifikasi log, pasangan setup → entry, trade & ringkasan."""
import io
from datetime import date, datetime, timezone

import pandas as pd

from tg_signal import method_journal as mj
from tg_signal.journal import to_xlsx

PRO = [mj.Spec("XAU_SMC_TD", "XAUUSD", 990022, "pro_live.log")]
MAC = [mj.Spec("XAU_H4_MAC", "XAUUSD", 1, "mac_live.log"), mj.Spec("XAU_H1_MAC", "XAUUSD", 2, "mac_live.log")]

PRO_LOG = """\
2026-11-16 08:51:43,416 INFO SELL ARMED: harga menyentuh POI M15 FVG 3879.49–3884.48 (bias EMA50 H1 searah), tunggu CHoCH M5
2026-11-16 09:00:00,000 INFO HTTP Request: GET https://example/ff_calendar_thisweek.json
2026-11-16 19:15:02,013 INFO SELL ARMED: harga menyentuh POI M15 OB 3868.44–3878.59 (bias EMA50 H1 searah), tunggu CHoCH M5
2026-11-16 19:40:00,000 INFO SELL CHoCH M5: close di bawah swing low 3871.20 (swing 16/11 19:20 WIB) · POI M15 OB
2026-11-16 19:45:00,719 INFO ORDER DEMO SELL LIMIT @ 3869.89 SL 3876.16 TP 3851.07 (risiko 63 pips) | POI M15 OB (ticket 4158002860)
2026-11-16 21:40:00,420 INFO TUTUP 4158002860 SELL → SL -1.00R (-6.27 USD) | entry 3869.89 exit 3876.16
"""
MAC_LOG = """\
2026-11-17 12:11:20Z START mac_live: XAU_H4_MAC, XAU_H1_MAC · risiko 0.5%/trade
2026-11-17 13:00:22Z [XAU_H1_MAC] OPEN SELL 0.01 lot @ 3861.739 SL jarak 41.721 risiko 0.84% #4166164206
2026-11-18 00:54:57Z (dry) [XAU_H1_MAC] BREAKEVEN #4166164206 (sempat +0.5R): SL 3903.46 -> 3861.739
2026-11-18 01:00:10Z [XAU_H1_MAC] BREAKEVEN #4166164206 (sempat +0.5R): SL 3903.46 -> 3861.739
"""


def test_classify():
    assert mj.classify("SELL ARMED: harga menyentuh POI M15 FVG 1–2, tunggu CHoCH M5") == "SETUP"
    assert mj.classify("SELL CHoCH M5: close di bawah swing low 3871.20") == "KONFIRMASI"
    assert mj.classify("ORDER GAGAL SELL LIMIT: retcode") == "ERROR"
    assert mj.classify("PENDING SELL @ 3870 dibatalkan: 12 bar tanpa fill") == "BATAL"
    assert mj.classify("OPENING RANGE XAUUSD NY: tunggu close M5 di luar range") == "SETUP"
    assert mj.classify("START swing_live: 4 metode") is None


def test_events_and_setups(tmp_path):
    (tmp_path / "pro_live.log").write_text(PRO_LOG, encoding="utf-8")
    ev = mj.log_events(PRO, tmp_path)
    assert list(ev["Jenis"]) == ["SETUP", "SETUP", "KONFIRMASI", "ENTRY", "EXIT"]
    assert ev["Waktu (WIB)"].iloc[0] == datetime(2026, 11, 16, 8, 51, 43)          # log Python = WIB
    st = mj.setups(ev)
    assert list(st["Keputusan"]) == ["TIDAK ENTRY", "ENTRY"]
    assert "CHoCH M5 tidak terkonfirmasi" in st["Alasan / entry"].iloc[0]
    assert "CHoCH M5: close di bawah" in st["Alasan / entry"].iloc[1]
    assert st["Ticket"].iloc[1] == 4158002860


def test_shared_log_by_method_and_utc(tmp_path):
    (tmp_path / "mac_live.log").write_text(MAC_LOG, encoding="utf-8")
    ev = mj.log_events(MAC, tmp_path)
    assert list(ev["Jenis"]) == ["ENTRY", "KELOLA"]                                # START & (dry) dibuang
    assert set(ev["Metode"]) == {"XAU_H1_MAC"}
    assert ev["Waktu (WIB)"].iloc[0] == datetime(2026, 11, 17, 20, 0, 22)          # Z = UTC → +7


def test_frames_with_trades(tmp_path):
    (tmp_path / "pro_live.log").write_text(PRO_LOG, encoding="utf-8")
    trades = [{"ticket": 4158002860, "method": "XAU_SMC_TD", "symbol": "XAUUSD", "dir": "SELL", "lot": 0.01,
               "open": datetime(2026, 11, 16, 12, 49, tzinfo=timezone.utc), "entry": 3869.89, "sl": None,
               "tp": None, "close": datetime(2026, 11, 16, 14, 35, tzinfo=timezone.utc), "exit": 3876.16,
               "why": "SL", "usd": -6.27}]
    fr = mj.build_frames(PRO, date(2026, 11, 16), date(2026, 11, 16), trades=trades, data_dir=tmp_path)
    t = fr["Trades"].iloc[0]
    assert (t["SL"], t["TP"], t["R"]) == (3876.16, 3851.07, -1.0)                  # SL/TP dari baris ORDER
    assert t["Setup"].startswith("SELL ARMED") and t["Alasan entry"].startswith("ORDER DEMO")
    d = fr["Ringkasan Harian"].iloc[0]
    assert (d["Jml setup"], d["Entry"], d["Trade tutup"], d["Loss"]) == (2, 1, 1, 1)
    m = fr["Ringkasan Metode"].iloc[0]
    assert (m["Trade tutup"], m["Profit USD"]) == (1, -6.27)
    sheets = pd.read_excel(io.BytesIO(to_xlsx(fr)), sheet_name=None)
    assert list(sheets) == ["Trades", "Setup", "Kejadian", "Ringkasan Harian", "Ringkasan Metode"]
    assert mj.build_frames(PRO, date(2026, 11, 17), trades=trades, data_dir=tmp_path)["Trades"].empty
