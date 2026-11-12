from tg_signal.entry_plan import limit_filled, pending_expired, plan_entry

SL, TP = 3.0, 3.0


def test_buy_above_zone_is_limit_at_zero():
    p = plan_entry("BUY", 3974.0, 3970.0, bid=3974.95, ask=3975.11, sl_dist=SL, tp_dist=TP)
    assert p.kind == "LIMIT"
    assert p.price == 3974.0
    assert p.sl == 3967.0          # LAST − 30 pips
    assert p.tp == 3977.0          # ZERO + 30 pips


def test_buy_inside_zone_is_market():
    p = plan_entry("BUY", 3974.0, 3970.0, bid=3972.0, ask=3972.2, sl_dist=SL, tp_dist=TP)
    assert p.kind == "MARKET"
    assert p.price == 3972.2
    assert p.sl == 3967.0
    assert round(p.tp, 2) == 3975.2


def test_buy_below_last_but_above_sl_is_market():
    p = plan_entry("BUY", 3974.0, 3970.0, bid=3968.0, ask=3968.2, sl_dist=SL, tp_dist=TP)
    assert p.kind == "MARKET"


def test_buy_past_sl_rejected():
    p = plan_entry("BUY", 3974.0, 3970.0, bid=3966.9, ask=3967.1, sl_dist=SL, tp_dist=TP)
    assert p.kind == "REJECT" and p.reason == "PAST_SL"


def test_sell_below_zone_is_limit():
    p = plan_entry("SELL", 3984.0, 3988.0, bid=3982.68, ask=3982.85, sl_dist=SL, tp_dist=TP)
    assert p.kind == "LIMIT"
    assert p.price == 3984.0
    assert p.sl == 3991.0          # LAST + 30 pips
    assert p.tp == 3981.0


def test_sell_inside_zone_is_market_at_bid():
    p = plan_entry("SELL", 3984.0, 3988.0, bid=3985.0, ask=3985.2, sl_dist=SL, tp_dist=TP)
    assert p.kind == "MARKET" and p.price == 3985.0
    assert p.tp == 3982.0


def test_limit_fill_and_expiry():
    assert limit_filled("BUY", 3974.0, bid=3973.8, ask=3974.0)
    assert not limit_filled("BUY", 3974.0, bid=3974.0, ask=3974.2)
    assert limit_filled("SELL", 3984.0, bid=3984.0, ask=3984.2)
    assert pending_expired("BUY", 3974.0, bid=3977.0, ask=3977.2, tp_dist=TP)
    assert not pending_expired("BUY", 3974.0, bid=3976.9, ask=3977.1, tp_dist=TP)
    assert pending_expired("SELL", 3984.0, bid=3980.8, ask=3981.0, tp_dist=TP)
