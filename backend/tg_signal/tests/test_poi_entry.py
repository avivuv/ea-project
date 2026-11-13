from tg_signal.detectors.poi import zone_pois
from tg_signal.entry_plan import plan_poi

SL, TP = 3.0, 3.0


def test_buy_above_zone_limit_at_nearest_poi():
    pois = [(3895.2, 3893.6, "OB"), (3894.5, 3892.0, "FVG")]
    p = plan_poi("BUY", 3897.0, 3893.0, bid=3897.5, ask=3897.7, pois=pois, sl_dist=SL, tp_dist=TP)
    assert p.kind == "LIMIT" and p.price == 3895.2
    assert round(p.sl, 2) == 3892.2 and round(p.tp, 2) == 3898.2
    assert "OB" in p.reason


def test_buy_inside_zone_is_market():
    p = plan_poi("BUY", 3897.0, 3893.0, bid=3896.0, ask=3896.2, pois=[(3895.2, 3893.6, "OB")],
                 sl_dist=SL, tp_dist=TP)
    assert p.kind == "MARKET" and p.price == 3896.2
    assert round(p.sl, 2) == 3893.2


def test_buy_no_poi_falls_back_to_zero():
    p = plan_poi("BUY", 3897.0, 3893.0, bid=3898.0, ask=3898.2, pois=[], sl_dist=SL, tp_dist=TP)
    assert p.kind == "LIMIT" and p.price == 3897.0


def test_reprice_inside_zone_without_market():
    p = plan_poi("BUY", 3897.0, 3893.0, bid=3896.0, ask=3896.2, pois=[(3895.2, 3893.6, "OB")],
                 sl_dist=SL, tp_dist=TP, allow_market=False)
    assert p.kind == "LIMIT" and p.price == 3895.2
    q = plan_poi("BUY", 3897.0, 3893.0, bid=3896.0, ask=3896.2, pois=[], sl_dist=SL, tp_dist=TP,
                 allow_market=False)
    assert q.kind == "NONE"


def test_sell_limit_at_lowest_supply():
    pois = [(3900.83, 3903.58, "OB"), (3902.77, 3905.92, "OB")]
    p = plan_poi("SELL", 3901.0, 3905.0, bid=3900.13, ask=3900.30, pois=pois, sl_dist=SL, tp_dist=TP)
    assert p.kind == "LIMIT" and p.price == 3900.83
    assert round(p.sl, 2) == 3903.83 and round(p.tp, 2) == 3897.83


def test_past_sl_rejected():
    p = plan_poi("BUY", 3897.0, 3893.0, bid=3889.9, ask=3890.1, pois=[], sl_dist=SL, tp_dist=TP)
    assert p.kind == "REJECT"


def _bars(rows):
    o, h, l, c = zip(*rows)
    return list(o), list(h), list(l), list(c)


def test_zone_pois_finds_bullish_fvg_and_ob_in_zone():
    rows = [(3900, 3900.5, 3899.5, 3900)] * 5 + [
        (3896.0, 3896.2, 3894.0, 3894.2),   # bearish → OB
        (3894.2, 3897.5, 3894.1, 3897.4),   # impuls
        (3897.4, 3899.0, 3896.8, 3898.8),   # low > high 2 bar lalu → FVG 3896.2–3896.8
        (3898.8, 3899.2, 3898.5, 3899.0),
    ]
    found = zone_pois("BUY", *_bars(rows), zero=3897.0, last=3893.0)
    kinds = {k for _, _, k in found}
    assert {"FVG", "OB"} <= kinds
    fvg = next(p for p in found if p[2] == "FVG")
    assert fvg[0] == 3896.8 and fvg[1] == 3896.2


def test_zone_pois_drops_broken_poi():
    rows = [(3900, 3900.5, 3899.5, 3900)] * 5 + [
        (3896.0, 3896.2, 3894.0, 3894.2),
        (3894.2, 3897.5, 3894.1, 3897.4),
        (3897.4, 3899.0, 3896.8, 3898.8),
        (3898.8, 3898.9, 3893.0, 3893.5),   # close di bawah FVG & OB → keduanya gagal
    ]
    found = zone_pois("BUY", *_bars(rows), zero=3897.0, last=3893.0)
    assert not any(k in ("FVG", "OB") and prox >= 3896 for prox, _, k in found)
