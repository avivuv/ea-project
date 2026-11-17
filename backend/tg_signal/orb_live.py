"""
Runner live ORB New York (Opening Range Breakout) XAUUSD di akun DEMO.

    python -m tg_signal.orb_live --mode DEMO     # order sungguhan di akun demo (magic ORB_MAGIC)
    python -m tg_signal.orb_live --mode LOG      # hanya catat sinyal, tanpa order

Konfigurasi (backtest 17 Nov 2026, orb.py — PF 1.42 latih / 1.61 uji, DD ~6R, ~2 trade/minggu):
  opening range = high/low 15 menit pertama setelah NY buka 09:30 America/New_York
  (21:30 WIB musim dingin AS, 20:30 WIB musim panas) · breakout = close M5 pertama di luar range
  dalam 120 menit · harus searah bias EMA50 H1 (slope > 0.1 ATR14) · entry market · SL = sisi seberang
  range ∓ $0.1 · TP 2R · posisi ditutup paksa 6 jam setelah NY buka · maks 1 trade per hari.
Logika sinyal = orb.find_breakout / orb.bias_at / orb.plan_order (diverifikasi identik dengan backtest).
Kill switch bersama: file data/PAUSE → tidak ada order baru.
Marker chart: tiap bar M5 baru ditulis Common\Files\orb_area.csv (range 5 hari terakhir, breakout, posisi)
untuk indikator ProPOI (MT5).
Lot: ORB_LOT tetap (default 0.01), atau ORB_RISK_USD > 0 → lot dihitung dari risiko (min 0.01, maks ORB_MAX_LOT).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import time
from datetime import datetime, timezone

import pandas as pd

from tg_signal import orb
from tg_signal import settings
from tg_signal.executor import MT5Executor
from tg_signal.settings import _f, _i

log = logging.getLogger("tg_signal.orb")
ORB_MAGIC = _i("ORB_MAGIC", 990033)           # beda dari TG_MAGIC / PRO_MAGIC
ORB_LOT = _f("ORB_LOT", 0.01)
ORB_RISK_USD = _f("ORB_RISK_USD", 0)          # 0 = pakai ORB_LOT tetap
ORB_MAX_LOT = _f("ORB_MAX_LOT", 0.05)
HEARTBEAT = settings.DATA_DIR / "orb_heartbeat"
STATE_PATH = settings.DATA_DIR / "orb_live_state.json"
TRADES_PATH = settings.DATA_DIR / "orb_live_trades.csv"
LOOP_SEC = 5
CFG = orb.LIVE_CFG


def lot_for(risk_px: float) -> float:
    if ORB_RISK_USD <= 0:
        return ORB_LOT
    lot = math.floor(ORB_RISK_USD / (risk_px * 100) / 0.01) * 0.01     # 1 lot XAUUSD = 100 oz
    return round(min(max(lot, 0.01), ORB_MAX_LOT), 2)


class OrbTrader:
    def __init__(self, ex: MT5Executor, mode: str):
        self.ex, self.mode = ex, mode
        self.state = {"day": None, "done": False, "or": None, "pos": None}
        if STATE_PATH.exists():
            self.state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        self.last_m5 = None
        self.last_export = None

    def save(self) -> None:
        STATE_PATH.write_text(json.dumps(self.state, indent=1, default=str), encoding="utf-8")

    def step(self) -> None:
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
        or_end = op + pd.Timedelta(minutes=CFG.or_min)
        if self.state["done"] or now < or_end or now >= op + pd.Timedelta(minutes=orb.HOLD_MIN):
            return
        m5 = self.ex.rates_df("M5", 100)
        if m5.index[-1] == self.last_m5:
            return
        self.last_m5 = m5.index[-1]
        m1 = self.ex.rates_df("M1", 400)
        sig = orb.find_breakout(m1, m5, op, CFG)
        if sig is None:
            return
        if self.state["or"] is None:
            self.state["or"] = [sig["or_hi"], sig["or_lo"]]
            log.info("OPENING RANGE NY %s: high %.2f low %.2f (lebar %.2f) — tunggu close M5 di luar range s/d %s WIB",
                     day, sig["or_hi"], sig["or_lo"], sig["or_hi"] - sig["or_lo"],
                     (or_end + pd.Timedelta(minutes=orb.BREAK_WAIT)).tz_convert("Asia/Jakarta").strftime("%H:%M"))
            self.save()
        if "dir" not in sig:
            if m5.index[-1] >= or_end + pd.Timedelta(minutes=orb.BREAK_WAIT) - pd.Timedelta(minutes=5):
                log.info("ORB NY %s: tidak ada breakout dalam %d menit — selesai hari ini", day, orb.BREAK_WAIT)
                self.state["done"] = True
                self.save()
            return
        self.state["done"] = True                       # hanya breakout pertama yang dihitung
        self.save()
        d, is_buy = sig["dir"], sig["dir"] == "BUY"
        if sig["bar"] != m5.index[-1]:
            log.info("ORB NY %s: breakout %s terjadi di bar %s (sebelum runner jalan) — dilewati", day, d,
                     sig["bar"].tz_convert("Asia/Jakarta").strftime("%H:%M"))
            return
        h1 = self.ex.rates_df("H1", 500)
        bias_ok = orb.bias_at(orb.h1_bias(h1), sig["close_time"], is_buy)
        info = f"{d} breakout range {sig['or_lo']:.2f}–{sig['or_hi']:.2f}"
        if not bias_ok:
            log.info("ORB NY %s: %s tapi bias EMA50 H1 tidak searah — dilewati (hari selesai)", day, info)
            return
        if settings.PAUSE_FILE.exists():
            log.info("ORB NY %s: %s — dilewati (PAUSE)", day, info)
            return
        tick = self.ex.tick()
        price = tick.ask if is_buy else tick.bid
        plan = orb.plan_order(sig, price)
        if plan is None:
            log.info("ORB NY %s: %s — risiko < $%.0f, dilewati", day, info, orb.RISK_MIN)
            return
        sl, tp, risk = plan
        lot = lot_for(risk)
        rec = {"dir": d, "price": price, "sl": sl, "tp": tp, "risk": risk, "lot": lot, "ticket": None,
               "placed": datetime.now(timezone.utc).isoformat(),
               "close_at": (op + pd.Timedelta(minutes=orb.HOLD_MIN)).isoformat()}
        txt = (f"{d} MARKET @ {price:.2f} SL {sl:.2f} TP {tp:.2f} (risiko {risk / settings.PIP_SIZE:.0f} pips, "
               f"lot {lot}) | range {sig['or_lo']:.2f}–{sig['or_hi']:.2f}")
        if self.mode == "DEMO":
            try:
                f = self.ex.open_market_at(d, lot, sl, tp, comment="orb")
                rec.update(ticket=f.ticket, price=f.price)
            except RuntimeError as e:
                log.error("ORDER GAGAL %s: %s", txt, e)
                return
        self.state["pos"] = rec
        self.save()
        log.info("ORDER %s %s (ticket %s)", self.mode, txt, rec["ticket"] or "paper")

    def export_markers(self, now: pd.Timestamp, days: int = 5) -> None:
        """Tulis Common\\Files\\orb_area.csv untuk indikator ProPOI. Format 8 kolom (sama pro_poi.csv):
        ORB,,status,t_open,low,high,t_akhir_breakout,flag   flag 0 bentuk range · 1 tunggu breakout ·
                                                            2 tanpa breakout · 3 breakout → order · 4 breakout, bias ✗
        ORBBRK,dir,,t_close_bar,close,0,0,bias_ok            bar M5 breakout
        ORBORD,dir,position,t_placed,entry,sl,tp,1           posisi ORB terbuka
        Waktu = epoch jam server MT5."""
        off = int(settings.MT5_UTC_OFFSET_H * 3600)
        ep = lambda t: int(pd.Timestamp(t).timestamp()) + off
        m1 = self.ex.rates_df("M1", 1440 * (days + 3))
        m5 = self.ex.rates_df("M5", 288 * (days + 3))
        bias = orb.h1_bias(self.ex.rates_df("H1", 600))
        rows = [f"HDR,,,{int(time.time()) + off},0,0,0,0"]
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
            or_end = op + pd.Timedelta(minutes=CFG.or_min)
            brk_end = or_end + pd.Timedelta(minutes=orb.BREAK_WAIT)
            stop = op + pd.Timedelta(minutes=orb.HOLD_MIN)
            sig = orb.find_breakout(m1[m1.index < stop], m5[m5.index < stop], op, CFG)
            if sig is None:                                 # range masih terbentuk
                part = m1[m1.index >= op]
                if part.empty:
                    continue
                rows.append(f"ORB,,RANGE,{ep(op)},{part.low.min():.2f},{part.high.max():.2f},{ep(or_end)},0")
                continue
            if "dir" in sig:
                ok = orb.bias_at(bias, sig["close_time"], sig["dir"] == "BUY")
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
        path = self.ex.common_files_dir() / "orb_area.csv"
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
            usd = round(sg * (exit_px - rec["price"]) * 100 * rec["lot"], 2)
        r = round(sg * (exit_px - rec["price"]) / rec["risk"], 2)
        log.info("TUTUP %s %s → %s %+.2fR (%+.2f USD) | entry %.2f exit %.2f", rec["ticket"] or "paper", d, why,
                 r, usd, rec["price"], exit_px)
        new = not TRADES_PATH.exists()
        with TRADES_PATH.open("a", newline="", encoding="utf-8") as fh:
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
    args = ap.parse_args()
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(settings.DATA_DIR / "orb_live.log", encoding="utf-8")])
    ex = MT5Executor(magic=ORB_MAGIC)
    ex.connect()
    st = ex.status()
    if args.mode == "DEMO" and not st["algo_trading"]:
        raise SystemExit("Tombol 'Algo Trading' di MT5 masih MATI — nyalakan dulu.")
    op = orb.session_open_utc(pd.Timestamp.now(tz="America/New_York").date())
    log.info("ORB %s login %s (demo=%s) saldo %.2f | %s | NY buka %s WIB | lot %s%s | magic %s",
             args.mode, st["login"], st["demo"], st["balance"], CFG.name,
             op.tz_convert("Asia/Jakarta").strftime("%H:%M"), ORB_LOT,
             f" (risiko ${ORB_RISK_USD:g}/trade)" if ORB_RISK_USD > 0 else "", ORB_MAGIC)
    trader = OrbTrader(ex, args.mode)
    try:
        while True:
            HEARTBEAT.touch()
            try:
                trader.step()
            except Exception:
                log.exception("siklus gagal")
            time.sleep(LOOP_SEC)
    finally:
        ex.shutdown()


if __name__ == "__main__":
    main()
