"""
EA swing trend-following (Donchian breakout) — eksekusi via MetaTrader5, HANYA akun DEMO.
Aturan sama persis dengan backtest `intraday.swing` (fungsi `signals` yang sama).

    python -m intraday.swing_live              # jalan terus (cek tiap 30 detik, aksi saat bar H1 baru)
    python -m intraday.swing_live --once       # satu kali cek + tampilkan status, tanpa order
    python -m intraday.swing_live --status     # status posisi & state

Per metode maksimal 1 posisi (dibedakan lewat magic number). Tidak menyentuh posisi EA scalping.
- Entry: market di awal bar H1 pertama setelah bar TF sinyal close.
- SL awal = 2 × ATR(14) TF sinyal; tanpa TP. Exit per metode (`EXITS`, studi `intraday.swing_exit_study`
  20 Nov 2026), diperbarui tiap bar H1 close, SL hanya bergeser searah profit:
    trail K   chandelier: ekstrem bid sejak bar entry − K × ATR (ATR saat entry, atau ATR TF terbaru bila live)
    be X      SL → harga entry setelah harga sempat +X R
  Bila harga sudah melewati level SL baru (tidak bisa dipasang) → tutup market (= backtest: stop kena di open
  bar berikutnya). Bila hanya terlalu dekat (stops level broker) → ditunda.
- Metode di `ENTRY_OFF`: tidak membuka posisi baru (posisi yang masih ada tetap dikelola).
- Lot = risiko RISK_PCT saldo; bila lot minimum berisiko > MAX_RISK_PCT → entry di-skip (dicatat).
State: tg_signal/data/swing_state.json · Log: tg_signal/data/swing_live.log
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from intraday import swing as sw
from tg_signal import mt5_conn, settings

RISK_PCT = 0.5
MAX_RISK_PCT = 2.0
MAX_HOLD_DAYS = 60
H1_BARS = 20000
POLL_SEC = 30
DEVIATION = 100

METHODS = [  # (id, simbol, nama variasi di intraday.swing — dipakai untuk SINYAL, magic)
    ("XAU_D1_DON20", "XAUUSD", "DONCHIAN_D1_n20_SL2ATR_trail3_trD1", 26111201),
    ("XAU_H4_DON55", "XAUUSD", "DONCHIAN_H4_n55_SL2ATR_trail4_trD1", 26111202),
    ("BTC_H4_DON55", "BTCUSD", "DONCHIAN_H4_n55_SL2ATR_trail4_trD1", 26111203),
    ("JPY_H4_DON55", "USDJPY", "DONCHIAN_H4_n55_SL2ATR_trail4_trD1", 26111204),
]
# Exit per metode (20 Nov 2026, studi swing_exit_study; sebelumnya trail3 / trail4 ATR saat entry):
#   XAU D1  tr3_live  avgR 0.450 → 0.495, PF 2.13 → 2.37, DD 8.8 → 8.1R
#   XAU H4  be1_tr5   avgR 0.285 → 0.430, PF 1.51 → 2.00, DD 19.4 → 15.9R
#   BTC H4  tr6_live  avgR 0.131 → 0.521, PF 1.21 → 1.73 (latih tetap tipis)
#   JPY H4  tidak ada exit yang kokoh → entry baru dimatikan
EXITS = {
    "XAU_D1_DON20": {"trail": 3, "live": True},
    "XAU_H4_DON55": {"trail": 5, "be": 1},
    "BTC_H4_DON55": {"trail": 6, "live": True},
    "JPY_H4_DON55": {"trail": 4},
}
ENTRY_OFF = {"JPY_H4_DON55"}
STATE_PATH = settings.DATA_DIR / "swing_state.json"
LOG_PATH = settings.DATA_DIR / "swing_live.log"
HEARTBEAT = settings.DATA_DIR / "swing_heartbeat"
PAUSE_FILE = settings.PAUSE_SWING    # ada (atau PAUSE global) → tidak ada entry baru (trailing tetap jalan)
VARIANTS = {v.name: v for v in sw.variants()}


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"last_signal": {}, "positions": {}, "last_bar": {}}


def save_state(st: dict) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


class Broker:
    def __init__(self):
        import MetaTrader5 as mt5
        self.mt5 = mt5
        self.symbols = sorted({s for _, s, _, _ in METHODS})
        mt5_conn.connect(self.symbols, strict=False)     # path terminal dari settings + tolak non-DEMO

    def ensure_connected(self) -> str | None:
        """Sambung ulang bila terminal MT5 sempat restart (pesan log bila reconnect, raise bila belum siap)."""
        return mt5_conn.ensure(self.symbols, strict=False)

    def h1(self, symbol: str) -> pd.DataFrame:
        """Bar H1 yang SUDAH close (bar berjalan dibuang), waktu UTC, spread dalam harga."""
        mt5 = self.mt5
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, H1_BARS)
        if r is None or len(r) < 100:
            raise RuntimeError(f"data H1 {symbol} gagal: {mt5.last_error()}")
        df = pd.DataFrame(r)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True) - timedelta(hours=settings.MT5_UTC_OFFSET_H)
        df["spread"] = df["spread"] * mt5.symbol_info(symbol).point
        df = df.set_index("time")[["open", "high", "low", "close", "spread"]]
        return df.iloc[:-1]                     # bar terakhir = bar yang sedang berjalan

    def current_bar_time(self, symbol: str) -> pd.Timestamp:
        r = self.mt5.copy_rates_from_pos(symbol, self.mt5.TIMEFRAME_H1, 0, 1)
        return pd.Timestamp(int(r[0]["time"]), unit="s", tz="UTC") - timedelta(hours=settings.MT5_UTC_OFFSET_H)

    def position(self, symbol: str, magic: int):
        pos = [p for p in (self.mt5.positions_get(symbol=symbol) or ()) if p.magic == magic]
        return pos[0] if pos else None

    def lot_for(self, symbol: str, sl_dist: float) -> tuple[float, float]:
        """(lot, risiko % saldo). lot 0 bila lot minimum terlalu berisiko."""
        i, bal = self.mt5.symbol_info(symbol), self.mt5.account_info().balance
        loss_per_lot = sl_dist / i.trade_tick_size * i.trade_tick_value
        lot = math.floor(bal * RISK_PCT / 100 / loss_per_lot / i.volume_step) * i.volume_step
        lot = max(lot, i.volume_min)
        risk = lot * loss_per_lot / bal * 100
        if risk > MAX_RISK_PCT:
            return 0.0, risk
        return round(min(lot, i.volume_max), 2), risk

    def _filling(self, symbol: str) -> int:
        fm, mt5 = self.mt5.symbol_info(symbol).filling_mode, self.mt5
        return mt5.ORDER_FILLING_FOK if fm & 1 else (mt5.ORDER_FILLING_IOC if fm & 2 else mt5.ORDER_FILLING_RETURN)

    def open(self, symbol: str, direction: int, lot: float, sl_dist: float, magic: int, comment: str):
        mt5 = self.mt5
        tk, d = mt5.symbol_info_tick(symbol), mt5.symbol_info(symbol).digits
        price = tk.ask if direction > 0 else tk.bid
        sl = price - sl_dist if direction > 0 else price + sl_dist
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(lot),
               "type": mt5.ORDER_TYPE_BUY if direction > 0 else mt5.ORDER_TYPE_SELL,
               "price": round(price, d), "sl": round(sl, d), "tp": 0.0, "deviation": DEVIATION,
               "magic": magic, "comment": comment[:31], "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": self._filling(symbol)}
        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"order gagal {symbol}: {mt5.last_error() if res is None else (res.retcode, res.comment)}")
        return res

    def modify_sl(self, pos, sl: float) -> None:
        mt5 = self.mt5
        d = mt5.symbol_info(pos.symbol).digits
        res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": pos.symbol, "position": pos.ticket,
                              "sl": round(sl, d), "tp": pos.tp, "magic": pos.magic})
        if res is not None and res.retcode == mt5.TRADE_RETCODE_NO_CHANGES:
            return                                  # SL sudah di level itu
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"modify SL gagal #{pos.ticket}: {mt5.last_error() if res is None else (res.retcode, res.comment)}")

    def close(self, pos, comment: str) -> None:
        mt5 = self.mt5
        tk = mt5.symbol_info_tick(pos.symbol)
        buy = pos.type == mt5.POSITION_TYPE_BUY
        res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol, "position": pos.ticket,
                              "volume": pos.volume, "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
                              "price": tk.bid if buy else tk.ask, "deviation": DEVIATION, "magic": pos.magic,
                              "comment": comment[:31], "type_time": mt5.ORDER_TIME_GTC,
                              "type_filling": self._filling(pos.symbol)})
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"close gagal #{pos.ticket}")


def tf_atr_now(h1: pd.DataFrame, tf: str, now_bar: pd.Timestamp) -> float:
    """ATR(14) bar TF terakhir yang SUDAH close per open bar H1 `now_bar` (= `atr_o[j+1]` di swing_exit_study)."""
    b = sw.resample(h1, tf)
    b = b[b.index + pd.Timedelta(sw.RULES[tf]) <= now_bar]
    return float(sw.atr(b).iloc[-1]) if len(b) else float("nan")


def trail_sl(pos, h1: pd.DataFrame, info: dict, spec: dict, sl_atr: float, is_buy: bool, digits: int,
             atr_now: float | None = None) -> float | None:
    """SL baru menurut aturan exit `spec` (sama dengan swing_exit_study.simulate). None = tidak berubah.

    - trail K: ekstrem bid sejak bar entry ∓ K × ATR (ATR saat entry = sl_dist / sl_atr, atau `atr_now` bila live)
    - be X: harga entry bila harga sempat +X × sl_dist
    Dibandingkan SETELAH dibulatkan ke digit simbol: tanpa ini SL yang secara pembulatan sama dengan
    SL sekarang tetap dikirim → broker menolak (retcode 10025 'No changes') tiap 30 detik."""
    since = h1[h1.index >= pd.Timestamp(info["entry_bar"])]
    if since.empty:
        return None
    d = 1 if is_buy else -1
    ext = since.high.max() if is_buy else since.low.min()
    entry, dist = pos.price_open, info["sl_dist"]
    cand = []
    if spec.get("trail"):
        atr_v = atr_now if spec.get("live") else dist / sl_atr
        if atr_v is not None and atr_v == atr_v:
            cand.append(ext - d * spec["trail"] * atr_v)
    if spec.get("be") is not None and d * (ext - entry) >= spec["be"] * dist:
        cand.append(entry)
    if not cand:
        return None
    new = round(max(cand) if is_buy else min(cand), digits)
    half = 0.5 * 10 ** -digits
    return new if d * (new - pos.sl) > half else None


def price_past(bk: Broker, pos, sl: float, is_buy: bool) -> bool:
    """True bila harga sekarang sudah melewati level SL (SL tidak mungkin dipasang)."""
    tk = bk.mt5.symbol_info_tick(pos.symbol)
    return tk.bid <= sl if is_buy else tk.ask >= sl


def sl_valid(bk: Broker, pos, sl: float, is_buy: bool) -> tuple[bool, str]:
    """SL harus di sisi yang benar dari harga sekarang dengan jarak ≥ stops level (aturan broker)."""
    mt5 = bk.mt5
    i, tk = mt5.symbol_info(pos.symbol), mt5.symbol_info_tick(pos.symbol)
    min_dist = max(i.trade_stops_level, i.trade_freeze_level) * i.point
    if is_buy:
        ok = tk.bid - sl >= min_dist
        return ok, f"bid {tk.bid} − SL {sl} < jarak min {min_dist:g}"
    ok = sl - tk.ask >= min_dist
    return ok, f"SL {sl} − ask {tk.ask} < jarak min {min_dist:g}"


def step(bk: Broker, st: dict, dry: bool = False) -> None:
    cache: dict[str, pd.DataFrame] = {}
    for mid, sym, vname, magic in METHODS:
        v = VARIANTS[vname]
        try:
            if sym not in cache:
                cache[sym] = bk.h1(sym)
            h1 = cache[sym]
            now_bar = bk.current_bar_time(sym)             # open time bar H1 berjalan = waktu entry backtest
            pos = bk.position(sym, magic)
            info = st["positions"].get(mid)

            # ── kelola posisi ───────────────────────────────────────────
            if pos is not None:
                if info is None or info.get("ticket") != pos.ticket:     # posisi tanpa state (mis. restart)
                    info = {"ticket": pos.ticket, "sl_dist": abs(pos.price_open - pos.sl),
                            "entry_bar": str(now_bar.floor("h")), "dir": 1 if pos.type == 0 else -1}
                    st["positions"][mid] = info
                    log(f"[{mid}] adopsi posisi #{pos.ticket} tanpa state")
                is_buy = pos.type == bk.mt5.POSITION_TYPE_BUY
                age = datetime.now(timezone.utc) - datetime.fromtimestamp(pos.time, timezone.utc)
                if age > timedelta(days=MAX_HOLD_DAYS):
                    if not dry:
                        bk.close(pos, f"{mid} max hold")
                    log(f"[{mid}] tutup #{pos.ticket}: hold > {MAX_HOLD_DAYS} hari")
                    continue
                spec = EXITS[mid]
                atr_now = tf_atr_now(h1, v.tf, now_bar) if spec.get("live") else None
                new = trail_sl(pos, h1, info, spec, v.sl_atr, is_buy, bk.mt5.symbol_info(sym).digits, atr_now)
                if new is not None:
                    ok, why = sl_valid(bk, pos, new, is_buy)
                    if not ok and price_past(bk, pos, new, is_buy):   # = backtest: stop kena di open bar ini
                        if not dry:
                            bk.close(pos, f"{mid} stop")
                        log(f"[{mid}] tutup #{pos.ticket}: harga sudah melewati SL baru {new} ({why})")
                        continue
                    if not ok:                     # terlalu dekat harga (stops level) → tunggu, jangan spam error
                        if info.get("sl_skip") != new:
                            info["sl_skip"] = new
                            log(f"[{mid}] trailing #{pos.ticket} ditunda: {why}")
                        continue
                    info.pop("sl_skip", None)
                    if not dry:
                        bk.modify_sl(pos, new)
                    log(f"[{mid}] trailing #{pos.ticket} SL {pos.sl:.3f} → {new:.3f}")
                continue
            if info is not None:
                log(f"[{mid}] posisi #{info['ticket']} sudah tertutup (SL/trailing)")
                st["positions"].pop(mid, None)

            # ── cari sinyal baru ────────────────────────────────────────
            sig = sw.signals(h1, v, sw.d1_trend_series(h1))
            sig = sig[sig.index <= now_bar]
            if sig.empty:
                continue
            t_sig, row = sig.index[-1], sig.iloc[-1]
            if t_sig != now_bar or st["last_signal"].get(mid) == str(t_sig):
                continue                                   # bukan sinyal di batas bar ini / sudah diproses
            st["last_signal"][mid] = str(t_sig)
            if mid in ENTRY_OFF:
                log(f"[{mid}] entry dimatikan (ENTRY_OFF): sinyal {t_sig:%Y-%m-%d %H:%M}Z dilewati")
                continue
            if settings.is_paused(PAUSE_FILE):
                log(f"[{mid}] PAUSE: sinyal {t_sig:%Y-%m-%d %H:%M}Z dilewati")
                continue
            dr, sl_dist = int(row.dir), float(row.sl_dist)
            lot, risk = bk.lot_for(sym, sl_dist)
            side = "BUY" if dr > 0 else "SELL"
            if lot <= 0:
                log(f"[{mid}] SKIP sinyal {side} {t_sig:%Y-%m-%d %H:%M}Z: lot minimum berisiko {risk:.1f}% saldo "
                    f"(> {MAX_RISK_PCT}%) — SL {sl_dist:.3f}")
                continue
            if dry:
                log(f"[{mid}] (dry) akan {side} {lot} lot, SL jarak {sl_dist:.3f}, risiko {risk:.2f}%")
                continue
            res = bk.open(sym, dr, lot, sl_dist, magic, f"swing {mid}")
            st["positions"][mid] = {"ticket": res.order, "sl_dist": sl_dist, "entry_bar": str(now_bar),
                                    "dir": dr, "lot": lot, "risk_pct": round(risk, 2)}
            log(f"[{mid}] OPEN {side} {lot} lot @ {res.price} SL jarak {sl_dist:.3f} risiko {risk:.2f}% #{res.order}")
        except Exception as e:                              # satu metode gagal tidak menghentikan yang lain
            log(f"[{mid}] ERROR {e}")


def status(bk: Broker, st: dict) -> None:
    acc = bk.mt5.account_info()
    print(f"Akun demo {acc.login} saldo {acc.balance:.2f} {acc.currency} equity {acc.equity:.2f}")
    for mid, sym, vname, magic in METHODS:
        v = VARIANTS[vname]
        h1 = bk.h1(sym)
        sig = sw.signals(h1, v, sw.d1_trend_series(h1))
        last = sig.iloc[-1] if len(sig) else None
        lot, risk = bk.lot_for(sym, float(last.sl_dist)) if last is not None else (0, 0)
        pos = bk.position(sym, magic)
        p = f"posisi #{pos.ticket} {'BUY' if pos.type == 0 else 'SELL'} {pos.volume} @ {pos.price_open} SL {pos.sl} P/L {pos.profit:+.2f}" if pos else "tanpa posisi"
        ls = f"sinyal terakhir {'BUY' if last.dir > 0 else 'SELL'} {sig.index[-1]:%Y-%m-%d %H:%M}Z" if last is not None else "-"
        ex = " ".join(f"{k}={val}" for k, val in EXITS[mid].items()) + (" · ENTRY OFF" if mid in ENTRY_OFF else "")
        print(f"  {mid:13s} {sym:7s} {p} | {ls} | lot saat ini {lot} (risiko {risk:.1f}%) | exit {ex}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="satu kali cek, tanpa order")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    bk, st = Broker(), load_state()
    if a.status or a.once:
        status(bk, st)
        if a.once:
            step(bk, st, dry=True)
        return
    log(f"START swing_live: {len(METHODS)} metode, risiko {RISK_PCT}%/trade (maks {MAX_RISK_PCT}%), akun DEMO")
    last_seen: dict[str, str] = {}
    while True:
        try:
            if msg := bk.ensure_connected():
                log(msg)
            changed = False
            for sym in {m[1] for m in METHODS}:
                cb = str(bk.current_bar_time(sym))
                if last_seen.get(sym) != cb:
                    last_seen[sym] = cb; changed = True
            if changed:
                step(bk, st)
                save_state(st)
        except Exception as e:
            log(f"ERROR loop: {e}")
        HEARTBEAT.write_text(datetime.now(timezone.utc).isoformat())
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
