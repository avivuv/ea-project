from datetime import datetime, timezone

from tg_signal.risk import RiskLimits, RiskState, check
from tg_signal.run_live import day_start_utc

LIM = RiskLimits(max_zone_distance=15, max_spread_pips=5, max_positions=1,
                 max_trades_day=40, daily_loss_usd=30, daily_profit_usd=10)


def test_ok():
    assert check("BUY", 4162, 0.7, RiskState(spread_pips=1.7), LIM) == (True, "")


def test_rejections():
    assert check("BUY", 4162, 0.7, RiskState(1.7, paused=True), LIM)[1] == "PAUSED"
    assert check("BUY", 4162, 20, RiskState(1.7), LIM)[1] == "ZONE_TOO_FAR"
    assert check("BUY", 4162, 0.7, RiskState(6.0), LIM)[1] == "SPREAD_TOO_WIDE"
    assert check("BUY", 4162, 0.7, RiskState(1.7, pnl_today_usd=-30), LIM)[1] == "DAILY_LOSS_LIMIT"
    assert check("BUY", 4162, 0.7, RiskState(1.7, pnl_today_usd=10), LIM)[1] == "DAILY_PROFIT_TARGET"
    assert check("BUY", 4162, 0.7, RiskState(1.7, pnl_today_usd=9.99), LIM) == (True, "")
    assert check("BUY", 4162, 0.7, RiskState(1.7, trades_today=40), LIM)[1] == "MAX_TRADES_DAY"
    assert check("SELL", 4142, 0.7, RiskState(1.7, open_positions=[("BUY", 0.0)]), LIM)[1] == "MAX_POSITIONS"
    assert check("BUY", 4162, 0.7, RiskState(1.7, price_age_sec=30), LIM)[1] == "PRICE_STALE"


def test_day_start_is_wib_midnight():
    # 11 Nov 2026 03:00 UTC = 10:00 WIB → hari dimulai 10 Nov 17:00 UTC
    assert day_start_utc(datetime(2026, 11, 11, 3, tzinfo=timezone.utc)) == datetime(2026, 11, 10, 17, tzinfo=timezone.utc)
    # 18:00 UTC = 01:00 WIB tgl 12 → hari dimulai 11 Nov 17:00 UTC
    assert day_start_utc(datetime(2026, 11, 11, 18, tzinfo=timezone.utc)) == datetime(2026, 11, 11, 17, tzinfo=timezone.utc)


def test_daily_target_counts_floating():
    from tg_signal.risk import target_hit
    assert target_hit(6.0, 4.0, 10)          # 6 tertutup + 4 floating = 10 → tutup
    assert not target_hit(6.0, 3.9, 10)
    assert target_hit(0.0, 10.5, 10)         # trade pertama belum TP tapi floating sudah 10.5
    assert not target_hit(8.0, 5.0, 0)       # 0 = nonaktif
