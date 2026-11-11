import pytest

from tg_signal.price_resolver import resolve_level, resolve_zone


# Tabel SIGNAL_SPEC §2
@pytest.mark.parametrize("ref, direction, a, b, zero, last", [
    (4165.30, "BUY", 62, 58, 4162, 4158),
    (4199.50, "BUY", 2, 98, 4202, 4198),
    (4201.20, "SELL", 98, 2, 4198, 4202),
    (4148.00, "SELL", 42, 46, 4142, 4146),
    (4103.00, "BUY", 5, 1, 4105, 4101),
    (4097.00, "SELL", 99, 3, 4099, 4103),
])
def test_resolve_zone_spec_table(ref, direction, a, b, zero, last):
    z = resolve_zone(direction, a, b, ref)
    assert (z.zero, z.last) == (zero, last)
    assert z.flags == []
    assert z.width == 4


def test_far_zone_has_large_distance():
    z = resolve_zone("BUY", 62, 58, 4130.0)
    assert (z.zero, z.last) == (4162, 4158)
    assert z.distance > 15


def test_distance_zero_inside_zone():
    z = resolve_zone("BUY", 62, 58, 4160.0)
    assert z.distance == 0


def test_mid_top_bottom():
    z = resolve_zone("SELL", 42, 46, 4140.0)
    assert z.mid == 4144
    assert (z.bottom, z.top) == (4142, 4146)


def test_order_suspect_flag():
    # BUY seharusnya angka pertama di atas
    z = resolve_zone("BUY", 58, 62, 4160.0)
    assert "ZONE_ORDER_SUSPECT" in z.flags


def test_width_suspect_flag():
    z = resolve_zone("SELL", 40, 55, 4145.0)
    assert "ZONE_WIDTH_SUSPECT" in z.flags


def test_resolve_level_invalid():
    with pytest.raises(ValueError):
        resolve_level(100, 4150.0)
