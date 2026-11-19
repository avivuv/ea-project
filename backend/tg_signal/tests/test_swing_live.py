"""Exit runner swing_live (trail_sl + tf_atr_now) harus sama dengan simulator studi swing_exit_study."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from intraday import swing as sw
from intraday import swing_exit_study as ses
from intraday.swing_live import EXITS, tf_atr_now, trail_sl


def fake_h1(n: int = 24 * 200, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    c = 2000 + np.cumsum(rng.normal(0.0, 4, n))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) + rng.uniform(0, 3, n)
    lo = np.minimum(o, c) - rng.uniform(0, 3, n)
    return pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c, "spread": 0.0}, index=t)


def replay(h1: pd.DataFrame, i: int, d: int, dist: float, v: sw.V, spec: dict) -> tuple[int, float]:
    """Tiru step(): tiap bar H1 close → cek SL kena di bar itu, lalu hitung SL baru dari bar yang sudah close."""
    o, h, l = h1.open.to_numpy(), h1.high.to_numpy(), h1.low.to_numpy()
    pos = SimpleNamespace(price_open=o[i], sl=o[i] - d * dist)
    info = {"entry_bar": str(h1.index[i]), "sl_dist": dist}
    for j in range(i, len(h1) - 1):
        if (d > 0 and l[j] <= pos.sl) or (d < 0 and h[j] >= pos.sl):
            px = min(pos.sl, o[j]) if d > 0 else max(pos.sl, o[j])
            return j, d * (px - pos.price_open) / dist
        done = h1.iloc[: j + 1]
        atr_now = tf_atr_now(done, v.tf, h1.index[j + 1]) if spec.get("live") else None
        new = trail_sl(pos, done, info, spec, v.sl_atr, d > 0, 8, atr_now)
        if new is not None:
            pos.sl = new
    return -1, float("nan")


@pytest.mark.parametrize("mid", list(EXITS))
@pytest.mark.parametrize("d", [1, -1])
def test_runner_exit_matches_study(mid, d, monkeypatch):
    monkeypatch.setattr(sw, "MIN_SPREAD", 0.0)
    monkeypatch.setattr(sw, "SLIP", 0.0)
    h1 = fake_h1(seed=3 if d > 0 else 4)
    tf = "D1" if mid.startswith("XAU_D1") else "H4"
    v = sw.V("DONCHIAN", tf, 20, 2, "trail3", "-")
    spec = EXITS[mid]
    b = sw.resample(h1, tf)
    aux = {"atr": ses.tf_on_h1(h1, b, sw.atr(b), tf), "close": ses.tf_on_h1(h1, b, b.close, tf)}
    i = 24 * 40
    dist = 2 * aux["atr"][i]
    sig = pd.DataFrame({"dir": [d], "sl_dist": [dist]}, index=[h1.index[i]])
    tr = ses.simulate(h1, sig, v, spec, aux)
    assert len(tr) == 1 and tr.why.iloc[0] == "SL", "trade uji harus selesai lewat SL"
    j, r = replay(h1, i, d, dist, v, spec)
    assert j == i + tr.hold_h.iloc[0] - 1
    assert r == pytest.approx(tr.r.iloc[0], abs=1e-6)
