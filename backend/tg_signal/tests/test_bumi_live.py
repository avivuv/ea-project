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


def replay_be(df: pd.DataFrame, be_r: float) -> list[tuple]:
    """Seperti replay() + breakeven: setelah close bar k, bila sempat +be_r R -> SL = entry (berlaku bar k+1)."""
    from tg_signal.bumi_live import be_reached
    ind = bd.indicators(df)
    h, l, c = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
    out, pos = [], None                       # pos = [dir, sl, k entry, entry, dist]
    for k in range(len(df)):
        exited = False
        if pos is not None:
            d, sl, kin, entry, dist = pos
            if k > kin and ((d > 0 and l[k] <= sl) or (d < 0 and h[k] >= sl)):
                exited = True
            elif k > kin and ind["up"][-d][k]:
                exited = True
            elif be_reached(df.iloc[: k + 1], str(df.index[kin]), entry, d, dist, be_r):
                pos[1] = entry
            if exited:
                pos = None
                out[-1] = out[-1] + (df.index[k],)
        if pos is None and not exited:
            d, dist = bd.live_signal(ind, k, SL_ATR)
            if d:
                pos = [d, c[k] - d * dist, k, c[k], dist]
                out.append((df.index[k], d))
    return out


@pytest.mark.skipif(not H1.exists(), reason="data H1 XAUUSD tidak ada")
def test_replay_be_matches_exit_study():
    from tg_signal.bumi_exit_study import events, simulate
    df = resample(bd.load_pair("XAUUSD"), "4h")
    df = df[df.index >= "2020-01-01"]
    ind = bd.indicators(df)
    bt = simulate(df, ind, events(df, ind), {"be": 0.5})
    live = replay_be(df, 0.5)
    assert len(live) == len(bt) > 50
    for (t_in, d, *t_out), (_, row) in zip(live, bt.iterrows()):
        assert t_in == row.t_in and d == row.dir
        if t_out:
            assert t_out[0] == row.t_out


def test_be_reached_sell_and_buy():
    from tg_signal.bumi_live import be_reached
    idx = pd.date_range("2026-11-17 12:00", periods=4, freq="h", tz="UTC")
    df = pd.DataFrame({"high": [100, 101, 99, 98], "low": [98, 95, 90, 94]}, index=idx)
    sig = str(idx[0])                                   # bar sinyal tidak dihitung
    assert be_reached(df, sig, 100.0, -1, 20.0, 0.5)    # low 90 = +10 = 0.5R
    assert not be_reached(df, sig, 100.0, -1, 21.0, 0.5)
    assert not be_reached(df, sig, 99.0, 1, 10.0, 0.5)  # high maks 101 = +2 < 5
    assert not be_reached(df, sig, 100.0, -1, 20.0, None)
    assert not be_reached(df.iloc[:1], sig, 100.0, -1, 1.0, 0.5)
