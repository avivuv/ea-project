"""
Runner live ORB New York (Opening Range Breakout) di akun DEMO — satu proses per instrumen.

    python -m tg_signal.orb_live --mode DEMO                    # XAUUSD (default)
    python -m tg_signal.orb_live --mode DEMO --symbol ETHUSD    # ETHUSD
    python -m tg_signal.orb_live --mode LOG --symbol ETHUSD     # hanya catat sinyal, tanpa order

Konfigurasi per instrumen (SPECS; backtest 17 Nov 2026, orb.py / orb_deep.py):
  XAUUSD : range 15 mnt setelah NY buka 09:30 America/New_York · breakout close M5 ≤ 120 mnt · harus searah
           bias EMA50 H1 (slope > 0.1 ATR14) · SL sisi seberang range ∓ $0.1 · TP 2R
           (PF 1.42 latih / 1.61 uji, DD ~6R, ~2 trade/minggu) · lot tetap 0.01 (ORB_LOT) atau ORB_RISK_USD
  ETHUSD : range 30 mnt · tanpa filter bias · SL ∓ $0.6 · TP 2R (PF 1.30 / 1.28, spread 2× masih 1.24 / 1.18,
           ~4 trade/minggu) · lot dari risiko ORB_ETHUSD_RISK_USD (default $15)
  Semua  : entry market · posisi ditutup paksa 6 jam setelah NY buka · maks 1 trade per hari ·
           NY buka 21:30 WIB (musim dingin AS) / 20:30 WIB (musim panas), DST otomatis.
Logika sinyal = orb.find_breakout / orb.bias_at / orb.plan_order (diverifikasi identik dengan backtest).
Pause: file data/PAUSE (global) atau data/PAUSE_ORB (semua instrumen ORB) → tidak ada order baru.
Marker chart: tiap bar M5 baru ditulis Common\\Files\\orb_area.csv (XAUUSD) / orb_area_<simbol>.csv
(range 5 hari terakhir, breakout, posisi) untuk indikator ProPOI (MT5).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from tg_signal import orb
from tg_signal import settings
from tg_signal.executor import MT5Executor
from tg_signal.settings import _f, _i

log = logging.getLogger("tg_signal.orb")
LOOP_SEC = 5


@dataclass(frozen=True)
class Spec:
    symbol: str
    cfg: orb.Cfg
    sl_buf: float           # harga di luar sisi range
    risk_min: float         # risiko minimum (harga)
    magic: int
    lot: float              # lot tetap bila risk_usd <= 0
    risk_usd: float         # > 0 → lot dihitung dari risiko
    max_lot: float
    suffix: str             # akhiran nama file (XAUUSD: "" → nama lama tetap)

    def path(self, stem: str, ext: str) -> Path:
        return settings.DATA_DIR / f"{stem}{self.suffix}{ext}"

    @property
    def log_path(self) -> Path:
        return self.path("orb_live", ".log")

    @property
    def state_path(self) -> Path:
        return self.path("orb_live_state", ".json")

    @property
    def trades_path(self) -> Path:
        return self.path("orb_live_trades", ".csv")

    @property
    def heartbeat(self) -> Path:
        return self.path("orb_heartbeat", "")

    @property
    def marker_file(self) -> str:
        return f"orb_area{self.suffix}.csv"

    @property
    def lot_text(self) -> str:
        return f"risiko ${self.risk_usd:g}/trade" if self.risk_usd > 0 else f"lot {self.lot}"


SPECS = {
    "XAUUSD": Spec("XAUUSD", orb.LIVE_CFG, 0.1, 1.0, _i("ORB_MAGIC", 990033), _f("ORB_LOT", 0.01),
                   _f("ORB_RISK_USD", 0), _f("ORB_MAX_LOT", 0.05), ""),
    "ETHUSD": Spec("ETHUSD", orb.Cfg("ny", 30, "bar", "market", "opp", "2", "none", "none"), 0.6, 6.0,
                   _i("ORB_ETHUSD_MAGIC", 990034), _f("ORB_ETHUSD_LOT", 0.1), _f("ORB_ETHUSD_RISK_USD", 15),
                   _f("ORB_ETHUSD_MAX_LOT", 2.0), "_ethusd"),
}
# kompatibilitas (dashboard lama / impor lain)
ORB_MAGIC, ORB_LOT, ORB_RISK_USD = SPECS["XAUUSD"].magic, SPECS["XAUUSD"].lot, SPECS["XAUUSD"].risk_usd


def lot_for(spec: Spec, risk_px: float, info) -> float:
    """Lot dari risiko dolar (kontrak & langkah lot dari info simbol MT5); tanpa risk_usd → lot tetap."""
    step = info.volume_step or 0.01
    if spec.risk_usd <= 0:
        lot = spec.lot
    else:
        lot = math.floor(spec.risk_usd / (risk_px * info.trade_contract_size) / step + 1e-9) * step
    lot = min(max(lot, info.volume_min), spec.max_lot)
    return round(lot, 2)


class OrbTrader:
    def __init__(self, ex: MT5Executor, mode: str, spec: Spec):
        self.ex, self.mode, self.spec, self.cfg = ex, mode, spec, spec.cfg
        self.state = {"day": None, "done": False, "or": None, "pos": None}
        if spec.state_path.exists():
            self.state = json.loads(spec.state_path.read_text(encoding="utf-8"))
        self.last_m5 = None
        self.last_export = None

    def save(self) -> None:
        self.spec.state_path.write_text(json.dumps(self.state, indent=1, default=str), encoding="utf-8")

    def step(self) -> None:
        sym, cfg = self.spec.symbol, self.cfg
        now = pd.Timestamp.now(tz="UTC")
        self.manage(now)
        m5_last = self.ex.rates_df("M5", 3).index[-1]
        if m5_last != self.last_export:
            self.last_export = m5_last
            try:
                self.export_markers(now)
            except Exception:
                log.exception("gagal menulis marker ORB")
        day = now.tz_convert("America/New_York").date()
        if pd.Timestamp(day).weekday() >= 5:
            return
        op = orb.session_open_utc(day)
        if self.state["day"] != str(day):
            self.state.update({"day": str(day), "done": False, "or": None})
            self.save()
        or_end = op + pd.Timedelta(minutes=cfg.or_min)
        if self.state["done"] or now < or_end or now >= op + pd.Timedelta(minutes=orb.HOLD_MIN):
            return
        m5 = self.ex.rates_df("M5", 100)
        if m5.index[-1] == self.last_m5:
            return
        self.last_m5 = m5.index[-1]
        m1 = self.ex.rates_df("M1", 400)
        sig = orb.find_breakout(m1, m5, op, cfg)
        if sig is None:
            return
        if self.state["or"] is None:
            self.state["or"] = [sig["or_hi"], sig["or_lo"]]
            log.info("OPENING RANGE %s NY %s: high %.2f low %.2f (lebar %.2f) — tunggu close M5 di luar range "
                     "s/d %s WIB", sym, day, sig["or_hi"], sig["or_lo"], sig["or_hi"] - sig["or_lo"],
                     (or_end + pd.Timedelta(minutes=orb.BREAK_WAIT)).tz_convert("Asia/Jakarta").strftime("%H:%M"))
            self.save()
        if "dir" not in sig:
            if m5.index[-1] >= or_end + pd.Timedelta(minutes=orb.BREAK_WAIT) - pd.Timedelta(minutes=5):
                log.info("ORB %s %s: tidak ada breakout dalam %d menit — selesai hari ini", sym, day,
                         orb.BREAK_WAIT)
                self.state["done"] = True
                self.save()
            return
        self.state["done"] = True                       # hanya breakout pertama yang dihitung
        self.save()
        d, is_buy = sig["dir"], sig["dir"] == "BUY"
        if sig["bar"] != m5.index[-1]:
            log.info("ORB %s %s: breakout %s terjadi di bar %s (sebelum runner jalan) — dilewati", sym, day, d,
                     sig["bar"].tz_convert("Asia/Jakarta").strftime("%H:%M"))
            return
        info = f"{d} breakout range {sig['or_lo']:.2f}–{sig['or_hi']:.2f}"
        if cfg.bias == "with":
            h1 = self.ex.rates_df("H1", 500)
            if not orb.bias_at(orb.h1_bias(h1), sig["close_time"], is_buy):
                log.info("ORB %s %s: %s tapi bias EMA50 H1 tidak searah — dilewati (hari selesai)", sym, day, info)
                return
        if settings.is_paused(settings.PAUSE_ORB):
            log.info("ORB %s %s: %s — dilewati (PAUSE)", sym, day, info)
            return
        tick = self.ex.tick()
        price = tick.ask if is_buy else tick.bid
        plan = orb.plan_order(sig, price, float(cfg.tp), self.spec.sl_buf, self.spec.risk_min)
        if plan is None:
            log.info("ORB %s %s: %s — risiko < %.2f, dilewati", sym, day, info, self.spec.risk_min)
            return
        sl, tp, risk = plan
        lot = lot_for(self.spec, risk, self.ex.info)
        rec = {"dir": d, "price": price, "sl": sl, "tp": tp, "risk": risk, "lot": lot, "ticket": None,
               "placed": datetime.now(timezone.utc).isoformat(),
               "close_at": (op + pd.Timedelta(minutes=orb.HOLD_MIN)).isoformat()}
        usd_risk = risk * self.ex.info.trade_contract_size * lot
        txt = (f"{sym} {d} MARKET @ {price:.2f} SL {sl:.2f} TP {tp:.2f} (risiko {risk:.2f} ≈ ${usd_risk:.2f}, "
               f"lot {lot}) | range {sig['or_lo']:.2f}–{sig['or_hi']:.2f}")
        if self.mode == "DEMO":
            try:
                f = self.ex.open_market_at(d, lot, sl, tp, comment=f"orb {sym}")
                rec.update(ticket=f.ticket, price=f.price)
            except RuntimeError as e:
                log.error("ORDER GAGAL %s: %s", txt, e)
                return
        self.state["pos"] = rec
        self.save()
        log.info("ORDER %s %s (ticket %s)", self.mode, txt, rec["ticket"] or "paper")

    def export_markers(self, now: pd.Timestamp, days: int = 5) -> None:
        """Tulis Common\\Files\\orb_area[_simbol].csv untuk indikator ProPOI. Format 8 kolom (sama pro_poi.csv):
        ORB,,status,t_open,low,high,t_akhir,flag   flag 0 bentuk range (t_akhir = akhir range) · 1 tunggu
                                                   breakout · 2 tanpa breakout · 3 breakout → order ·
                                                   4 breakout, bias ✗   (t_akhir = batas breakout)
        ORBBRK,dir,,t_close_bar,close,0,0,bias_ok  bar M5 breakout
        ORBORD,dir,position,t_placed,entry,sl,tp,1 posisi ORB terbuka
        Waktu = epoch jam server MT5."""
        cfg = self.cfg
        off = int(settings.MT5_UTC_OFFSET_H * 3600)
        ep = lambda t: int(pd.Timestamp(t).timestamp()) + off
        m1 = self.ex.rates_df("M1", 1440 * (days + 3))
        m5 = self.ex.rates_df("M5", 288 * (days + 3))
        bias = orb.h1_bias(self.ex.rates_df("H1", 600)) if cfg.bias == "with" else None
        rows = [f"HDR,,{cfg.or_min},{int(time.time()) + off},0,0,0,0"]
        ny_today = now.tz_convert("America/New_York").normalize()
        k = 0
        for back in range(0, 14):
            day = (ny_today - pd.Timedelta(days=back)).date()
            if pd.Timestamp(day).weekday() >= 5:
                continue
            op = orb.session_open_utc(day)
            if op > now:
                continue
            k += 1
            if k > days:
                break
            or_end = op + pd.Timedelta(minutes=cfg.or_min)
            brk_end = or_end + pd.Timedelta(minutes=orb.BREAK_WAIT)
            stop = op + pd.Timedelta(minutes=orb.HOLD_MIN)
            sig = orb.find_breakout(m1[m1.index < stop], m5[m5.index < stop], op, cfg)
            if sig is None:                                 # range masih terbentuk
                part = m1[m1.index >= op]
                if part.empty:
                    continue
                rows.append(f"ORB,,RANGE,{ep(op)},{part.low.min():.2f},{part.high.max():.2f},{ep(or_end)},0")
                continue
            if "dir" in sig:
                ok = True if bias is None else orb.bias_at(bias, sig["close_time"], sig["dir"] == "BUY")
                flag = 3 if ok else 4
                close = float(m5.loc[sig["bar"], "close"])
                rows.append(f"ORBBRK,{sig['dir']},,{ep(sig['close_time'])},{close:.2f},0,0,{int(ok)}")
            else:
                flag = 1 if now < brk_end else 2
            rows.append(f"ORB,,RANGE,{ep(op)},{sig['or_lo']:.2f},{sig['or_hi']:.2f},{ep(brk_end)},{flag}")
        rec = self.state.get("pos")
        if rec:
            rows.append(f"ORBORD,{rec['dir']},position,{ep(rec['placed'])},{rec['price']:.2f},{rec['sl']:.2f},"
                        f"{rec['tp']:.2f},1")
        path = self.ex.common_files_dir() / self.spec.marker_file
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(rows) + "\n", encoding="ascii")
        tmp.replace(path)

    def manage(self, now: pd.Timestamp) -> None:
        rec = self.state.get("pos")
        if not rec:
            return
        d, sg = rec["dir"], (1 if rec["dir"] == "BUY" else -1)
        exit_px = usd = why = None
        if self.mode == "DEMO":
            if rec["ticket"] in self.ex.open_tickets():
                if now >= pd.Timestamp(rec["close_at"]):
                    if not self.ex.close_position(rec["ticket"], comment="orb time stop"):
                        log.error("gagal menutup posisi %s (time stop)", rec["ticket"])
                        return
                    log.info("TIME STOP %s: posisi ditutup 6 jam setelah NY buka", rec["ticket"])
                else:
                    return
            c = self.ex.closed_info(rec["ticket"])
            if c is None:
                return
            exit_px, usd, why = c.exit_price, c.profit_usd, c.reason
            if why not in ("TP", "SL") and now >= pd.Timestamp(rec["close_at"]):
                why = "TIME"
        else:
            tick = self.ex.tick()
            px = tick.bid if sg == 1 else tick.ask
            if sg * (px - rec["sl"]) <= 0:
                exit_px, why = rec["sl"], "SL"
            elif sg * (px - rec["tp"]) >= 0:
                exit_px, why = rec["tp"], "TP"
            elif now >= pd.Timestamp(rec["close_at"]):
                exit_px, why = px, "TIME"
            else:
                return
            usd = round(sg * (exit_px - rec["price"]) * self.ex.info.trade_contract_size * rec["lot"], 2)
        r = round(sg * (exit_px - rec["price"]) / rec["risk"], 2)
        log.info("TUTUP %s %s %s → %s %+.2fR (%+.2f USD) | entry %.2f exit %.2f", self.spec.symbol,
                 rec["ticket"] or "paper", d, why, r, usd, rec["price"], exit_px)
        path = self.spec.trades_path
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["mode", "ticket", "dir", "placed", "closed", "entry", "sl", "tp", "exit", "lot", "R",
                            "usd", "outcome"])
            w.writerow([self.mode, rec["ticket"], d, rec["placed"], now.isoformat(), rec["price"], rec["sl"],
                        rec["tp"], exit_px, rec["lot"], r, usd, why])
        self.state["pos"] = None
        self.save()


def main() -> None:
    ap = argparse.ArgumentParser(description="Runner live ORB New York (akun demo)")
    ap.add_argument("--mode", default="DEMO", choices=("LOG", "DEMO"))
    ap.add_argument("--symbol", default="XAUUSD", choices=tuple(SPECS))
    args = ap.parse_args()
    spec = SPECS[args.symbol]
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(spec.log_path, encoding="utf-8")])
    ex = MT5Executor(symbol=spec.symbol, magic=spec.magic)
    ex.connect()
    st = ex.status()
    if args.mode == "DEMO" and not st["algo_trading"]:
        raise SystemExit("Tombol 'Algo Trading' di MT5 masih MATI — nyalakan dulu.")
    op = orb.session_open_utc(pd.Timestamp.now(tz="America/New_York").date())
    log.info("ORB %s %s login %s (demo=%s) saldo %.2f | %s | NY buka %s WIB | %s | magic %s",
             spec.symbol, args.mode, st["login"], st["demo"], st["balance"], spec.cfg.name,
             op.tz_convert("Asia/Jakarta").strftime("%H:%M"), spec.lot_text, spec.magic)
    trader = OrbTrader(ex, args.mode, spec)
    try:
        while True:
            spec.heartbeat.touch()
            try:
                if msg := ex.ensure_connected():
                    log.warning(msg)
                trader.step()
            except Exception:
                log.exception("siklus gagal")
            time.sleep(LOOP_SEC)
    finally:
        ex.shutdown()


if __name__ == "__main__":
    main()
