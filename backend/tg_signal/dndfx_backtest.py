"""Backtest 3 dokumen model entry DNDFX di XAUUSD (riset, tanpa order).

1. BUMI      : SMA 5/13/21/34 — Cross Langsung / Menunggu Urutan x entry pas cross / koreksi+engulfing
               x TP RR 1:4 / tutup saat MA5 cross balik. SL tetap 100 pips ($10).
2. OTE Type  : struktur swing H1 (fractal 2) -> BOS -> Fibo leg (1 = asal leg, 0 = ujung leg).
               T1 limit di 0.62/0.705; T2 sentuh OTE -> CHoCH internal M15 -> limit 0.62 Fibo internal;
               T3 PDA (OB+FVG H1) di OTE, agresif limit / konfirmasi CHoCH M15; T4 counter: CHoCH M15
               di puncak leg -> limit 0.62 internal, SL di atas puncak, TP 0.5 Fibo besar.
3. SnD       : OB H1 + FVG (fresh), EMA50/200 H1 untuk trend, jam 07-22 WIB (00-15 UTC).
               S1/S2 limit langsung di OB; S3/S4 engulfing LTF lalu entry candle ketiga;
               S5/S6 CHoCH LTF + OB+FVG LTF -> limit di OB LTF, SL swing + 5 pips. RR 1:2 / 1:3.

Konvensi: harga bid; biaya = spread bar entry (dalam R). Bar yang menyentuh SL & TP sekaligus = SL.
Arah sell disimulasikan dengan cermin harga (o,h,l,c) -> (-o,-l,-h,-c) supaya logika cukup versi buy.

    python -m tg_signal.dndfx_backtest
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
SES_UTC = (0, 15)            # 07:00-22:00 WIB


# ---------------------------------------------------------------- util
def load(tf: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{tf}_XAUUSD.csv.gz")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "spread": "mean"}).dropna()


class Bars:
    """Array OHLC + versi cermin (index 1 = buy, -1 = sell)."""

    def __init__(self, df: pd.DataFrame):
        self.t = df.index
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.sp = df["spread"].to_numpy(float)
        self.m = {1: (o, h, l, c), -1: (-o, -l, -h, -c)}
        self.n = len(c)
        hr = df.index.hour
        self.ses = np.asarray((hr >= SES_UTC[0]) & (hr < SES_UTC[1]))
        sh, sl = fractals(h, l)
        self.lastsh = {1: last_conf(sh), -1: last_conf(sl)}   # swing high di ruang cermin


def fractals(h, l, n: int = 2):
    N, w = len(h), 2 * n + 1
    sh, sl = np.zeros(N, bool), np.zeros(N, bool)
    if N >= w:
        sh[n:N - n] = h[n:N - n] >= np.lib.stride_tricks.sliding_window_view(h, w).max(axis=1)
        sl[n:N - n] = l[n:N - n] <= np.lib.stride_tricks.sliding_window_view(l, w).min(axis=1)
    return sh, sl


def last_conf(flags, n: int = 2):
    """out[i] = index fractal terakhir yang sudah terkonfirmasi saat bar i-1 close (-1 bila belum ada)."""
    N = len(flags)
    out = np.full(N, -1)
    idx = np.nonzero(flags)[0]
    pos = idx + n + 1
    ok = pos < N
    out[pos[ok]] = idx[ok]
    return np.maximum.accumulate(out)


def atr(h, l, c, p: int = 14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    return pd.Series(tr).rolling(p, min_periods=1).mean().to_numpy()


def exit_sim(o, h, l, c, i0, d, sl, tp, xsig=None, fill_bar: bool = True):
    """Posisi aktif sejak bar i0. fill_bar=True: i0 = bar fill limit (TP & exit sinyal baru dihitung mulai
    bar berikutnya). fill_bar=False: entry di open bar i0 (market setelah close bar sinyal) -> semua dicek
    sejak i0. -> (px, idx, alasan)."""
    n = len(c)
    start = i0
    if not fill_bar:
        i0 -= 1                      # bar "fill" semu = bar sinyal -> bar start dicek penuh (k > i0)
    for k in range(start, n):
        if d > 0:
            if l[k] <= sl:
                return (min(o[k], sl) if k > i0 else sl), k, "SL"
            if tp is not None and k > i0 and h[k] >= tp:
                return max(o[k], tp), k, "TP"
        else:
            if h[k] >= sl:
                return (max(o[k], sl) if k > i0 else sl), k, "SL"
            if tp is not None and k > i0 and l[k] <= tp:
                return min(o[k], tp), k, "TP"
        if xsig is not None and k > i0 and xsig[k]:
            return c[k], k, "X"
    return c[-1], n - 1, "END"


def rec(model, var, B: Bars, d, i_in, i_out, entry, sl, px, why, sign=1):
    """entry/sl/px di ruang cermin `sign`; R tidak berubah oleh pencerminan."""
    risk = abs(entry - sl)
    r =(px - entry) / risk if entry > sl else (entry - px) / risk
    return dict(model=model, var=var, dir="BUY" if d > 0 else "SELL", t_in=B.t[i_in], t_out=B.t[i_out],
                entry=sign * entry, sl=sign * sl, exit=sign * px, why=why, risk=risk,
                R=r - B.sp[i_in] / risk)


# ---------------------------------------------------------------- 1. BUMI
def bumi(df: pd.DataFrame, tf: str, sl_pct: float | None = None) -> list[dict]:
    """sl_pct=None -> SL tetap $10 (dokumen); angka -> SL = persen harga (cek robust lintas era harga)."""
    B = Bars(df)
    o, h, l, c = B.m[1]
    s = pd.Series(c)
    a, b, e, f = (s.rolling(p).mean().to_numpy() for p in (5, 13, 21, 34))
    up = {1: (a > b) & (a > e) & (a > f), -1: (a < b) & (a < e) & (a < f)}
    order = {1: (a > b) & (b > e) & (e > f), -1: (a < b) & (b < e) & (e < f)}
    ev = []
    for d in (1, -1):
        x = up[d]
        ev += [(k, d) for k in np.nonzero(x[1:] & ~x[:-1])[0] + 1]
    ev.sort()
    out = []
    for mode in ("cross", "urut"):
        for ent in ("langsung", "engulf"):
            for ex in ("RR4", "crossMA"):
                var = f"{tf}_{mode}_{ent}_{ex}"
                busy = -1
                for k, d in ev:
                    if k <= busy:
                        continue
                    O, H, L, C = B.m[d]
                    valid = up[d]
                    tb = None
                    j = k
                    while j < B.n and valid[j]:
                        if mode == "cross" or order[d][j]:
                            tb = j
                            break
                        j += 1
                    if tb is None:
                        continue
                    eb = tb if ent == "langsung" else None
                    if ent == "engulf":
                        j = tb + 1
                        while j < B.n and valid[j]:
                            if C[j - 1] < O[j - 1] and C[j] > O[j] and C[j] > H[j - 1]:
                                eb = j
                                break
                            j += 1
                    if eb is None or eb + 1 >= B.n:
                        continue
                    entry = C[eb]
                    dist = 10.0 if sl_pct is None else abs(entry) * sl_pct
                    sl = entry - dist
                    tp = entry + 4 * dist if ex == "RR4" else None
                    px, ko, why = exit_sim(O, H, L, C, eb + 1, 1, sl, tp, up[-d] if ex == "crossMA" else None,
                                           fill_bar=False)
                    out.append(rec("BUMI", var, B, d, eb, ko, entry, sl, px, why, d))
                    busy = ko
    return out


# ---------------------------------------------------------------- 2. OTE (Entry Models)
MINLEG = 1.5   # leg minimal = 1.5 x ATR14 H1


def h1_structure(h1: pd.DataFrame) -> dict:
    o, h, l, c = (h1[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    N = len(c)
    at = atr(h, l, c)
    sh, sl = fractals(h, l)
    S = dict(dir=np.zeros(N, int), a1=np.full(N, np.nan), a0=np.full(N, np.nan),
             a1i=np.full(N, -1), lid=np.full(N, -1))
    lsh = lsl = cur = None
    for k in range(N):
        j = k - 2
        if j >= 2:
            if sh[j]:
                lsh = [j, h[j], False]
            if sl[j]:
                lsl = [j, l[j], False]
        if cur is not None:
            cur[2] = max(cur[2], h[k]) if cur[0] > 0 else min(cur[2], l[k])
        if lsh and not lsh[2] and c[k] > lsh[1]:
            lsh[2] = True
            if lsl:
                i1 = lsl[0] + int(np.argmin(l[lsl[0]:k + 1]))
                cur = [1, l[i1], h[i1:k + 1].max(), i1, k]
        elif lsl and not lsl[2] and c[k] < lsl[1]:
            lsl[2] = True
            if lsh:
                i1 = lsh[0] + int(np.argmax(h[lsh[0]:k + 1]))
                cur = [-1, h[i1], l[i1:k + 1].min(), i1, k]
        if cur is not None and ((cur[0] > 0 and c[k] < cur[1]) or (cur[0] < 0 and c[k] > cur[1])):
            cur = None
        if cur is not None and abs(cur[2] - cur[1]) >= MINLEG * at[k]:
            S["dir"][k], S["a1"][k], S["a0"][k], S["a1i"][k], S["lid"][k] = cur
    # PDA (OB+FVG atau FVG) di dalam leg yang overlap zona 0.5-0.705, dihitung di ruang cermin
    S["pt"], S["pb"] = np.full(N, np.nan), np.full(N, np.nan)
    mir = {1: (o, h, l, c), -1: (-o, -l, -h, -c)}
    for k in np.nonzero(S["dir"])[0]:
        d = S["dir"][k]
        O, H, L, C = mir[d]
        a1, a0 = d * S["a1"][k], d * S["a0"][k]
        rng = a0 - a1
        z_lo, z_hi = a0 - 0.705 * rng, a0 - 0.5 * rng
        lo_i = S["a1i"][k] + 1
        best = None
        for m in range(lo_i, k):            # candle tengah FVG; m+1 <= k
            if L[m + 1] > H[m - 1]:
                top = L[m + 1]
                bot = L[m - 1] if C[m - 1] < O[m - 1] else H[m - 1]
                if top >= z_lo and bot <= z_hi:
                    score = abs(top - (a0 - 0.62 * rng))
                    if best is None or score < best[0]:
                        best = (score, top, bot)
        if best:
            S["pt"][k], S["pb"][k] = best[1], best[2]
    return S


def ote(h1: pd.DataFrame, ex: pd.DataFrame, exname: str, types: tuple) -> list[dict]:
    S = h1_structure(h1)
    B = Bars(ex)
    h1t = h1.index.values
    k_of = np.searchsorted(h1t, (B.t - pd.Timedelta(hours=1)).values, side="right") - 1
    bph = {"H1": 1, "M15": 4, "M5": 12}[exname]
    out = []

    def leg(i):
        k = k_of[i]
        if k < 0 or S["dir"][k] == 0:
            return None
        d = S["dir"][k]
        return k, d, d * S["a1"][k], d * S["a0"][k], S["lid"][k]

    def tp_of(mode, a0, rng, entry, risk):
        return {"0": a0, "-0.27": a0 + 0.27 * rng, "RR2": entry + 2 * risk, "RR3": entry + 3 * risk}[mode]

    for typ in types:
        for tpm in ("0", "-0.27", "RR2", "RR3"):
            var = f"{exname}_{typ}_TP{tpm}"
            used, i = set(), 1
            while i < B.n - 1:
                g = leg(i)
                if g is None or g[4] in used:
                    i += 1
                    continue
                k, d, a1, a0, lid = g
                O, H, L, C = B.m[d]
                rng = a0 - a1
                nxt = None
                if typ in ("T1_062", "T1_0705", "T3_aggr"):
                    if typ == "T3_aggr":
                        if np.isnan(S["pt"][k]):
                            i += 1
                            continue
                        top, bot = S["pt"][k], S["pb"][k]
                        E = a0 - 0.62 * rng if (top - bot) > 0.25 * rng else min(top, a0 - 0.5 * rng)
                        SL = min(bot, E) - 0.05 * rng
                    else:
                        E = a0 - (0.62 if typ == "T1_062" else 0.705) * rng
                        SL = a1 - 0.05 * rng
                    if L[i] <= E:
                        used.add(lid)
                        entry = min(E, O[i])
                        if entry - SL > 0.2:
                            risk = entry - SL
                            tp = tp_of(tpm, a0, rng, entry, risk)
                            if tp > entry:
                                px, ko, why = exit_sim(O, H, L, C, i, 1, SL, tp)
                                out.append(rec("OTE", var, B, d, i, ko, entry, SL, px, why, d))
                                nxt = ko + 1
                    i = nxt or i + 1
                    continue

                if typ == "T4_counter":
                    # harga di sekitar puncak leg (>= level 0.2) lalu CHoCH berlawanan di LTF
                    j = B.lastsh[-d][i]      # swing low (ruang leg) terkonfirmasi
                    if j < 0 or i - j > 4 * bph or H[i - 1] < a0 - 0.2 * rng or C[i] >= L[j]:
                        i += 1
                        continue
                    used.add(lid)
                    top = H[max(0, i - 6 * bph):i + 1].max()
                    il = L[j:i + 1].min()
                    tp = a0 - 0.5 * rng
                    q = i + 1
                    while q < min(B.n, i + 1 + 8 * bph):
                        il = min(il, L[q - 1])
                        Es = il + 0.62 * (top - il)
                        if L[q] <= tp or H[q] > top:
                            break
                        if H[q] >= Es:
                            entry = max(Es, O[q])
                            SL = top + max(0.3, 0.05 * (top - il))
                            if entry < SL and tp < entry:
                                px, ko, why = exit_sim(O, H, L, C, q, -1, SL, tp)
                                out.append(rec("OTE", var, B, -d, q, ko, entry, SL, px, why, d))
                                nxt = ko + 1
                            break
                        q += 1
                    i = nxt or i + 1
                    continue

                # T2 / T3_conf : sentuh zona -> tunggu CHoCH internal di LTF
                if typ == "T2":
                    zone_top = a0 - 0.62 * rng
                else:
                    if np.isnan(S["pt"][k]):
                        i += 1
                        continue
                    zone_top = S["pt"][k]
                if L[i] > zone_top:
                    i += 1
                    continue
                used.add(lid)
                touch, il = i, L[i]
                m = i + 1
                choch = None
                while m < min(B.n, i + 16 * bph):
                    il = min(il, L[m])
                    if C[m] < a1:
                        break
                    j = B.lastsh[d][m]
                    if j >= touch - 3 * bph and C[m] > H[j]:
                        choch = m
                        break
                    m += 1
                if choch is None:
                    i = m + 1
                    continue
                if typ == "T3_conf":
                    entry = C[choch]
                    SL = il - max(0.3, 0.05 * rng)
                    risk = entry - SL
                    tp = tp_of(tpm, a0, rng, entry, risk)
                    if risk > 0.2 and tp > entry and choch + 1 < B.n:
                        px, ko, why = exit_sim(O, H, L, C, choch + 1, 1, SL, tp)
                        out.append(rec("OTE", var, B, d, choch, ko, entry, SL, px, why, d))
                        nxt = ko + 1
                    i = nxt or choch + 1
                    continue
                ih = H[choch]
                q = choch + 1
                while q < min(B.n, choch + 1 + 8 * bph):
                    Ei = ih - 0.62 * (ih - il)
                    SL = il - max(0.3, 0.05 * (ih - il))
                    if C[q - 1] < il:
                        break
                    if L[q] <= Ei:
                        entry = min(Ei, O[q])
                        risk = entry - SL
                        tp = tp_of(tpm, a0, rng, entry, risk)
                        if risk > 0.2 and tp > entry:
                            px, ko, why = exit_sim(O, H, L, C, q, 1, SL, tp)
                            out.append(rec("OTE", var, B, d, q, ko, entry, SL, px, why, d))
                            nxt = ko + 1
                        break
                    ih = max(ih, H[q])
                    if tpm in ("0", "-0.27") and ih >= a0:
                        break
                    q += 1
                i = nxt or q + 1
    return out


# ---------------------------------------------------------------- 3. SnD
def snd(h1: pd.DataFrame, ltf: pd.DataFrame, lname: str) -> list[dict]:
    o, h, l, c = (h1[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    cs = pd.Series(c)
    e50 = cs.ewm(span=50, adjust=False).mean().to_numpy()
    e200 = cs.ewm(span=200, adjust=False).mean().to_numpy()
    B = Bars(ltf)
    bph = {"M5": 12, "M15": 4}[lname]
    obs = []
    for m in range(1, len(c) - 1):
        t_av = h1.index[m + 1] + pd.Timedelta(hours=1)
        if t_av < B.t[0]:
            continue
        if c[m - 1] < o[m - 1] and l[m + 1] > h[m - 1]:
            obs.append((t_av, 1, h[m - 1], l[m - 1], e50[m + 1] > e200[m + 1]))
        if c[m - 1] > o[m - 1] and h[m + 1] < l[m - 1]:
            obs.append((t_av, -1, -l[m - 1], -h[m - 1], e50[m + 1] < e200[m + 1]))
    BUF = 0.5                                   # 5 pips
    MAXW = 72 * bph                             # umur antrian maks 72 jam
    out = []
    for t_av, d, prox, dist, trend in obs:
        O, H, L, C = B.m[d]
        i0 = int(np.searchsorted(B.t.values, t_av.to_datetime64()))
        iend = min(B.n, i0 + MAXW)
        sl0 = dist - BUF
        if prox - sl0 < 0.5:
            continue
        # sentuhan pertama (zona fresh) & batal bila TP RR2 tercapai lebih dulu
        touch = None
        for i in range(i0, iend):
            if L[i] <= prox:
                touch = i
                break
            if H[i] >= prox + 3 * (prox - sl0):
                break
        if touch is None:
            continue
        for sc in (1, 2, 3, 4, 5, 6):
            if sc in (2, 3, 5) and not trend:
                continue
            for rr in (2, 3):
                var = f"{lname}_S{sc}_RR{rr}"
                if sc in (1, 2):
                    tp0 = prox + rr * (prox - sl0)
                    # batal bila TP tersentuh sebelum fill
                    if H[i0:touch].max(initial=-np.inf) >= tp0 or not B.ses[touch]:
                        continue
                    entry = min(prox, O[touch])
                    if entry <= sl0:
                        continue
                    risk = entry - sl0
                    px, ko, why = exit_sim(O, H, L, C, touch, 1, sl0, entry + rr * risk)
                    out.append(rec("SnD", var, B, d, touch, ko, entry, sl0, px, why, d))
                elif sc in (3, 4):
                    for q in range(touch + 1, min(B.n - 1, touch + 3 * bph)):
                        if C[q] < dist:
                            break
                        if (C[q - 1] < O[q - 1] and C[q] > O[q] and C[q] > H[q - 1]
                                and min(L[q - 1], L[q]) <= prox):
                            if not B.ses[q + 1]:
                                break
                            entry = O[q + 1]
                            sl = min(dist, L[q - 1], L[q]) - BUF
                            risk = entry - sl
                            if risk > 0.3:
                                px, ko, why = exit_sim(O, H, L, C, q + 1, 1, sl, entry + rr * risk)
                                out.append(rec("SnD", var, B, d, q + 1, ko, entry, sl, px, why, d))
                            break
                else:  # 5, 6
                    il, ili = L[touch], touch
                    for q in range(touch + 1, min(B.n - 1, touch + 6 * bph)):
                        if L[q] < il:
                            il, ili = L[q], q
                        if C[q] < dist:
                            break
                        j = B.lastsh[d][q]
                        if not (j >= touch - 3 * bph and C[q] > H[j]):
                            continue
                        # CHoCH di q: cari OB+FVG LTF pada gerakan dari swing low ke q
                        ob = None
                        for x in range(q - 1, max(ili, 1) - 1, -1):
                            if C[x - 1] < O[x - 1] and L[x + 1] > H[x - 1]:
                                ob = (H[x - 1], L[x - 1])
                                break
                        if ob is None:
                            break
                        entry_lim = ob[0]
                        sl = min(il, ob[1]) - BUF
                        risk = entry_lim - sl
                        if risk < 0.3:
                            break
                        tp = entry_lim + rr * risk
                        for f in range(q + 1, min(B.n, q + 1 + 4 * bph)):
                            if L[f] <= entry_lim:
                                if B.ses[f]:
                                    entry = min(entry_lim, O[f])
                                    px, ko, why = exit_sim(O, H, L, C, f, 1, sl, entry + rr * (entry - sl))
                                    out.append(rec("SnD", var, B, d, f, ko, entry, sl, px, why, d))
                                break
                            if H[f] >= tp:
                                break
                        break
    return out


# ---------------------------------------------------------------- laporan
def stats(g: pd.DataFrame) -> dict:
    g = g.sort_values("t_out")
    r = g["R"]
    eq = r.cumsum()
    win, loss = r[r > 0].sum(), -r[r < 0].sum()
    half = g["t_in"].iloc[0] + (g["t_in"].iloc[-1] - g["t_in"].iloc[0]) / 2
    a, b = g[g.t_in < half]["R"], g[g.t_in >= half]["R"]
    pf = lambda x: x[x > 0].sum() / max(1e-9, -x[x < 0].sum())
    months = max(1.0, (g["t_in"].iloc[-1] - g["t_in"].iloc[0]).days / 30.4)
    return dict(n=len(g), per_bln=round(len(g) / months, 1), WR=round((r > 0).mean() * 100, 1),
                PF=round(win / max(loss, 1e-9), 2), sumR=round(r.sum(), 1), avgR=round(r.mean(), 3),
                maxDD=round((eq.cummax() - eq).max(), 1), PF_h1=round(pf(a), 2), PF_h2=round(pf(b), 2))


def report(tr: list[dict], title: str) -> pd.DataFrame:
    df = pd.DataFrame(tr)
    if df.empty:
        print(f"\n== {title}: tidak ada trade")
        return df
    rows = [dict(var=v, **stats(g)) for v, g in df.groupby("var")]
    res = pd.DataFrame(rows).sort_values("PF", ascending=False)
    print(f"\n== {title}  ({df.t_in.min():%Y-%m-%d} .. {df.t_in.max():%Y-%m-%d})")
    print(res.to_string(index=False))
    return res


def main() -> None:
    pd.set_option("display.width", 200)
    h1 = load("h1")
    m15 = load("m15")
    m5 = load("m5")
    all_tr, summ = [], []

    for name, tr in (("BUMI H1", bumi(h1, "H1")), ("BUMI H4", bumi(resample(h1, "4h"), "H4"))):
        summ.append(report(tr, name).assign(group=name))
        all_tr += tr

    tr = ote(h1, h1, "H1", ("T1_062", "T1_0705", "T3_aggr"))
    summ.append(report(tr, "OTE eksekusi H1 (2014-2026)").assign(group="OTE H1"))
    all_tr += tr
    tr = ote(h1, m15, "M15", ("T1_062", "T1_0705", "T2", "T3_aggr", "T3_conf", "T4_counter"))
    summ.append(report(tr, "OTE struktur H1 + eksekusi M15").assign(group="OTE M15"))
    all_tr += tr

    for lname, ldf in (("M5", m5), ("M15", m15)):
        tr = snd(h1, ldf, lname)
        summ.append(report(tr, f"SnD OB+FVG H1, LTF {lname}").assign(group=f"SnD {lname}"))
        all_tr += tr

    pd.DataFrame(all_tr).to_csv(DATA / "dndfx_trades.csv", index=False)
    pd.concat(summ).to_csv(DATA / "dndfx_summary.csv", index=False)
    print(f"\nsimpan: {DATA / 'dndfx_trades.csv'} , dndfx_summary.csv")


if __name__ == "__main__":
    main()
