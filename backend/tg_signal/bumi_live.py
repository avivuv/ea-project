"""
Runner BUMI (4 MA: SMA 5/13/21/34) — eksekusi via MetaTrader5, HANYA akun DEMO.
Aturan = config terpilih di `tg_signal.bumi_deep` (fungsi `indicators` & `live_signal` yang sama):

- Sinyal di bar TF (H4 / H1, di-resample dari H1) yang SUDAH close: MA5 baru saja pindah ke atas
  (buy) / bawah (sell) ketiga MA lain, dan EMA200 TF naik (buy) / turun (sell) dibanding 10 bar lalu.
- Entry market di awal bar berikutnya. SL = 3 x ATR14 TF. Tanpa TP.
- Exit: bar TF close dengan MA5 sudah di sisi berlawanan ketiga MA -> tutup market. Atau kena SL.
- Breakeven (18 Nov 2026, studi `bumi_exit_study`): setelah bar TF close di mana harga sempat mencapai
  +BE_R x jarak SL dari entry, SL dipindah ke harga entry. Bila harga sudah kembali melewati entry
  (SL tidak bisa dipasang), posisi ditutup market — sama dengan backtest (stop kena di open bar berikutnya).
- Bar yang sama dengan exit (SL / cross balik) tidak membuka posisi baru (sama dengan backtest).
- 1 posisi per metode (magic number). Lot = RISK_PCT saldo; skip bila lot minimum berisiko > MAX_RISK_PCT.
  Tidak ada batas risiko gabungan dengan runner lain (keputusan user 17 Nov 2026: akun demo, kumpulkan data).

    python -m tg_signal.bumi_live              # jalan terus (cek tiap 30 detik, aksi saat bar H1 baru)
    python -m tg_signal.bumi_live --once       # status + satu kali cek tanpa order
    python -m tg_signal.bumi_live --status

State: data/bumi_state.json · Log: data/bumi_live.log · Pause entry baru: file data/PAUSE_BUMI
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone

import pandas as pd

from intraday.swing_live import Broker as _SwingBroker, sl_valid
from tg_signal import settings
from tg_signal.bumi_deep import indicators, live_signal
from tg_signal.dndfx_backtest import resample

RISK_PCT = 0.5
MAX_RISK_PCT = 5.0      # hanya pengaman nilai aneh; lot min 0.01 di XAU H4 sudah ~1.7% (SL ~$80, saldo ~$5k)
SL_ATR = 3.0
BE_R = 0.5              # SL -> entry setelah harga sempat +0.5R (None = matikan)
POLL_SEC = 30
METHODS = [  # (id, simbol, TF, magic)
    ("XAU_H4_BUMI", "XAUUSD", "4h", 26111701),
    ("XAU_H1_BUMI", "XAUUSD", "1h", 26111702),
]
TF_HOURS = {"1h": 1, "4h": 4}
STATE_PATH = settings.DATA_DIR / "bumi_state.json"
LOG_PATH = settings.DATA_DIR / "bumi_live.log"
HEARTBEAT = settings.DATA_DIR / "bumi_heartbeat"
PAUSE_FILE = settings.DATA_DIR / "PAUSE_BUMI"       # ada -> tidak ada entry baru (exit tetap jalan)


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state() -> dict:
    st = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    for k in ("positions", "last_bar", "info"):
        st.setdefault(k, {})
    return st


def save_state(st: dict) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


class Broker(_SwingBroker):
    """Broker swing_live (cek akun DEMO, order, close) + lot sesuai konstanta BUMI."""

    def lot_for(self, symbol: str, sl_dist: float) -> tuple[float, float]:
        i, bal = self.mt5.symbol_info(symbol), self.mt5.account_info().balance
        loss_per_lot = sl_dist / i.trade_tick_size * i.trade_tick_value
        lot = math.floor(bal * RISK_PCT / 100 / loss_per_lot / i.volume_step) * i.volume_step
        lot = max(lot, i.volume_min)
        risk = lot * loss_per_lot / bal * 100
        if risk > MAX_RISK_PCT:
            return 0.0, risk
        return round(min(lot, i.volume_max), 2), risk


def closed_tf(h1: pd.DataFrame, tf: str, now_bar: pd.Timestamp) -> pd.DataFrame:
    """Bar TF yang sudah lengkap (h1 = bar H1 yang sudah close, now_bar = open bar H1 berjalan)."""
    df = h1 if tf == "1h" else resample(h1, tf)
    return df[df.index + pd.Timedelta(hours=TF_HOURS[tf]) <= now_bar]


def be_reached(df: pd.DataFrame, entry_bar: str, entry: float, d: int, sl_dist: float,
               be_r: float | None = BE_R) -> bool:
    """True bila sejak bar setelah bar sinyal (entry_bar) harga sempat bergerak >= be_r x sl_dist searah posisi."""
    if be_r is None or not sl_dist > 0:
        return False
    after = df[df.index > pd.Timestamp(entry_bar)]
    if after.empty:
        return False
    best = after.high.max() - entry if d > 0 else entry - after.low.min()
    return best >= be_r * sl_dist


def snapshot(ind: dict, df: pd.DataFrame, k: int) -> dict:
    a, b, e, f = (float(x[k]) for x in ind["ma"])
    st = "MA5 di atas semua" if ind["up"][1][k] else "MA5 di bawah semua" if ind["up"][-1][k] else "campur"
    slope = ind["ema"][k] - ind["ema"][k - 10]
    return {"bar": str(df.index[k]), "close": float(df.close.iloc[k]), "ma": [round(x, 3) for x in (a, b, e, f)],
            "ema200": round(float(ind["ema"][k]), 3), "slope": "naik" if slope > 0 else "turun",
            "state": st, "sl_dist": round(float(ind["atr"][k] * SL_ATR), 3)}


def step(bk: Broker, st: dict, dry: bool = False) -> None:
    cache: dict[str, pd.DataFrame] = {}
    for mid, sym, tf, magic in METHODS:
        try:
            if sym not in cache:
                cache[sym] = bk.h1(sym)
            now_bar = bk.current_bar_time(sym)
            df = closed_tf(cache[sym], tf, now_bar)
            if len(df) < 300:
                log(f"[{mid}] data {tf} kurang ({len(df)} bar)")
                continue
            k = len(df) - 1
            tbar = str(df.index[k])
            if st["last_bar"].get(mid) == tbar and not dry:
                continue                                    # bar TF ini sudah diproses
            ind = indicators(df)
            st["info"][mid] = snapshot(ind, df, k)
            pos = bk.position(sym, magic)
            info = st["positions"].get(mid)
            exited = False

            # ── kelola posisi ─────────────────────────────────────────────
            if pos is not None:
                d = 1 if pos.type == bk.mt5.POSITION_TYPE_BUY else -1
                if info is None or info.get("ticket") != pos.ticket:
                    info = {"ticket": pos.ticket, "dir": d, "entry_bar": tbar,
                            "sl_dist": abs(pos.price_open - pos.sl)}
                    st["positions"][mid] = info
                    log(f"[{mid}] adopsi posisi #{pos.ticket} tanpa state")
                if ind["up"][-d][k]:
                    if not dry:
                        bk.close(pos, f"bumi {mid} crossMA")
                        st["positions"].pop(mid, None)
                    log(f"[{mid}] EXIT cross MA #{pos.ticket} {'BUY' if d > 0 else 'SELL'} P/L {pos.profit:+.2f} "
                        f"(bar {df.index[k]:%Y-%m-%d %H:%M}Z close {df.close.iloc[k]:.3f})")
                    exited = True
                elif not info.get("be") and be_reached(df, info["entry_bar"], pos.price_open, d, info["sl_dist"]):
                    tag = f"[{mid}] BREAKEVEN #{pos.ticket} (sempat +{BE_R}R): SL {pos.sl} -> {pos.price_open}"
                    ok, why = sl_valid(bk, pos, pos.price_open, d > 0)
                    if dry:
                        log(f"(dry) {tag}" + ("" if ok else f" — tidak bisa ({why}) -> akan tutup market"))
                    elif ok:
                        bk.modify_sl(pos, pos.price_open)
                        info["be"] = True
                        log(tag)
                    else:
                        bk.close(pos, f"bumi {mid} BE")
                        st["positions"].pop(mid, None)
                        log(f"{tag} tidak bisa ({why}) -> tutup market P/L {pos.profit:+.2f}")
                        exited = True
            elif info is not None:
                log(f"[{mid}] posisi #{info['ticket']} sudah tertutup ({'BE/SL' if info.get('be') else 'SL'})")
                st["positions"].pop(mid, None)
                exited = True

            # ── sinyal baru ───────────────────────────────────────────────
            if pos is None and not exited:
                d, sl_dist = live_signal(ind, k, SL_ATR)
                if d:
                    side = "BUY" if d > 0 else "SELL"
                    st["info"][mid]["last_signal"] = f"{side} {df.index[k]:%Y-%m-%d %H:%M}Z"
                    if PAUSE_FILE.exists():
                        log(f"[{mid}] PAUSE: sinyal {side} {df.index[k]:%Y-%m-%d %H:%M}Z dilewati")
                    else:
                        lot, risk = bk.lot_for(sym, sl_dist)
                        if lot <= 0:
                            log(f"[{mid}] SKIP {side}: lot minimum berisiko {risk:.1f}% (> {MAX_RISK_PCT}%), "
                                f"SL {sl_dist:.3f}")
                        elif dry:
                            log(f"[{mid}] (dry) akan {side} {lot} lot, SL jarak {sl_dist:.3f}, risiko {risk:.2f}%")
                        else:
                            res = bk.open(sym, d, lot, sl_dist, magic, f"bumi {mid}")
                            st["positions"][mid] = {"ticket": res.order, "dir": d, "entry_bar": tbar,
                                                    "sl_dist": sl_dist, "lot": lot, "risk_pct": round(risk, 2)}
                            log(f"[{mid}] OPEN {side} {lot} lot @ {res.price} SL jarak {sl_dist:.3f} "
                                f"risiko {risk:.2f}% #{res.order}")
            if not dry:
                st["last_bar"][mid] = tbar
        except Exception as e:                              # satu metode gagal tidak menghentikan yang lain
            log(f"[{mid}] ERROR {e}")


def status(bk: Broker, st: dict) -> None:
    acc = bk.mt5.account_info()
    print(f"Akun demo {acc.login} saldo {acc.balance:.2f} {acc.currency} equity {acc.equity:.2f}")
    for mid, sym, tf, magic in METHODS:
        df = closed_tf(bk.h1(sym), tf, bk.current_bar_time(sym))
        ind = indicators(df)
        s = snapshot(ind, df, len(df) - 1)
        pos = bk.position(sym, magic)
        p = (f"posisi #{pos.ticket} {'BUY' if pos.type == 0 else 'SELL'} {pos.volume} @ {pos.price_open} "
             f"SL {pos.sl} P/L {pos.profit:+.2f}") if pos else "tanpa posisi"
        print(f"  {mid:12s} {sym} {tf}: {p} | bar {s['bar'][:16]} {s['state']}, EMA200 {s['slope']}, "
              f"SL bila sinyal {s['sl_dist']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="status + satu kali cek, tanpa order")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    bk, st = Broker(), load_state()
    if a.status or a.once:
        status(bk, st)
        if a.once:
            step(bk, st, dry=True)
        return
    log(f"START bumi_live: {', '.join(m[0] for m in METHODS)} · risiko {RISK_PCT}%/trade "
        f"(skip bila > {MAX_RISK_PCT}%) · SL {SL_ATR} ATR · BE {BE_R}R · akun DEMO")
    last_seen: dict[str, str] = {}
    while True:
        try:
            changed = False
            for sym in {m[1] for m in METHODS}:
                cb = str(bk.current_bar_time(sym))
                if last_seen.get(sym) != cb:
                    last_seen[sym] = cb
                    changed = True
            if changed:
                step(bk, st)
                save_state(st)
        except Exception as e:
            log(f"ERROR loop: {e}")
        HEARTBEAT.write_text(datetime.now(timezone.utc).isoformat())
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
