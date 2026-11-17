"""Runner BUMI harus mengambil keputusan yang sama dengan backtest bumi_deep (config terpilih)."""
import pandas as pd
import pytest

from tg_signal import bumi_deep as bd
from tg_signal.bumi_live import SL_ATR, closed_tf
from tg_signal.dndfx_backtest import DATA, resample

H1 = DATA / "h1_XAUUSD.csv.gz"


def replay(df: pd.DataFrame) -> list[tuple]:
    """Tiru step(): per bar close -> kelola posisi (SL intrabar / cross balik) lalu cari sinyal."""
    ind = bd.indicators(df)
    h, l = df.high.to_numpy(), df.low.to_numpy()
    out, pos = [], None                       # pos = (dir, sl, bar entry)
    for k in range(len(df)):
        exited = False
        if pos is not None:
            d, sl, kin = pos
            if k > kin and ((d > 0 and l[k] <= sl) or (d < 0 and h[k] >= sl)):
                pos, exited = None, True                       # SL kena di dalam bar k
            elif k > kin and ind["up"][-d][k]:
                pos, exited = None, True                       # cross balik di close bar k
            if exited:
                out[-1] = out[-1] + (df.index[k],)
        if pos is None and not exited:
            d, dist = bd.live_signal(ind, k, SL_ATR)
            if d:
                c = df.close.iloc[k]
                pos = (d, c - d * dist, k)
                out.append((df.index[k], d))
    return out


@pytest.mark.skipif(not H1.exists(), reason="data H1 XAUUSD tidak ada")
@pytest.mark.parametrize("tf", ["4h", "1h"])
def test_replay_matches_backtest(tf):
    df = resample(bd.load_pair("XAUUSD"), tf)
    if tf == "1h":
        df = df[df.index >= "2023-01-01"]
    bt = bd.run(df, "cross", "langsung", "atr3", "slope")
    live = replay(df)
    assert len(live) == len(bt)
    for (t_in, d, *t_out), (_, row) in zip(live, bt.iterrows()):
        assert t_in == row.t_in and d == row.dir
        if t_out:
            assert t_out[0] == row.t_out


def test_closed_tf_drops_unfinished_h4():
    idx = pd.date_range("2026-11-17 00:00", periods=6, freq="h", tz="UTC")
    h1 = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "spread": 0.1}, index=idx)
    # bar H1 berjalan = 06:00 -> H4 04:00 baru berisi 04-05, belum lengkap
    got = closed_tf(h1, "4h", pd.Timestamp("2026-11-17 06:00", tz="UTC"))
    assert list(got.index) == [pd.Timestamp("2026-11-17 00:00", tz="UTC")]
    got = closed_tf(h1, "1h", pd.Timestamp("2026-11-17 06:00", tz="UTC"))
    assert len(got) == 6
