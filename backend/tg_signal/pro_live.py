"""
Runner live strategi sendiri (pro_strategy, tanpa sinyal admin) di akun DEMO.

    python -m tg_signal.pro_live --mode DEMO     # order sungguhan di akun demo (magic PRO_MAGIC)
    python -m tg_signal.pro_live --mode LOG      # hanya catat setup, tanpa order

Konfigurasi (hasil backtest 13 Nov 2026, lihat pro_check.py):
  bias EMA50 H1 (kemiringan > 0.1 ATR) · POI M15 (FVG/OB/IFVG) · tanpa premium/discount · tanpa syarat sapuan ·
  konfirmasi CHoCH M5 · entry limit di FVG M5 (tanpa FVG → market) · RR 1:3 · semua sesi ·
  SL 10–100 pips · 1 posisi per arah · maks 3 trade/hari/arah · stop setelah 2 loss/hari/arah.

Cara kerja: tiap bar M5 baru, PRO_BARS bar terakhir disimulasikan ulang dengan logika yang SAMA
persis dengan backtest (pro_strategy.run_side). Bila simulasi baru saja memasang pending / entry
market di bar terakhir → order yang sama dikirim ke MT5. Pending dibatalkan setelah 12 bar M5,
bila harga sudah sampai level TP sebelum terisi, atau saat jendela news. SL/TP ikut di order.
News: ±PRO_NEWS_MIN menit dari event HIGH impact USD (kalender Forex Factory minggu ini).
Pause: file data/PAUSE (global) atau data/PAUSE_PRO → tidak ada order baru.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from tg_signal import pro_strategy as ps
from tg_signal import settings
from tg_signal.detectors.news_calendar import high_impact_times
from tg_signal.executor import MT5Executor

log = logging.getLogger("tg_signal.pro")
CFG = ps.Cfg("ema", False, False, "fvg", 3.0, False, False, min_pb=1.0)
# min_pb 1.0: pullback ke POI ≥ 1 ATR H1 (pro_pb_check 17 Nov 2026: PF 1.40/1.58 → 1.86/1.83, DD 20R → 12R)
EMA_SPAN, BIAS_TF = 50, 60
MIN_SLOPE = 0.1            # EMA50 H1 harus bergerak > 0.1 ATR / 3 bar (pro_sl_analysis: DD 34R → 16R di uji)
HEARTBEAT = settings.DATA_DIR / "pro_heartbeat"
STATE_PATH = settings.DATA_DIR / "pro_live_state.json"
TRADES_PATH = settings.DATA_DIR / "pro_live_trades.csv"
CHOCH_SHOW_BARS = 288          # marker CHoCH M5 yang ditampilkan: 24 jam terakhir
CHOCH_SHOW_MAX = 8             # maks per arah
LOOP_SEC = 5


def news_block(index: pd.DatetimeIndex, events: list[datetime], minutes: float) -> np.ndarray:
    """True untuk bar M5 yang (sebagian) berada dalam ±minutes dari event."""
    block = np.zeros(len(index), bool)
    if minutes <= 0 or not events:
        return block
    t = index.values.astype("datetime64[ns]")
    for e in events:
        e64 = np.datetime64(e.replace(tzinfo=None), "ns")
        lo, hi = e64 - np.timedelta64(int(minutes), "m"), e64 + np.timedelta64(int(minutes), "m")
        block |= (t + np.timedelta64(5, "m") > lo) & (t <= hi)
    return block


class ProTrader:
    def __init__(self, ex: MT5Executor, mode: str):
        self.ex, self.mode = ex, mode
        self.state = {"live": {}, "used": []}
        if STATE_PATH.exists():
            self.state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        self.last_bar = None

    def save(self) -> None:
        self.state["used"] = self.state["used"][-500:]
        STATE_PATH.write_text(json.dumps(self.state, indent=1, default=str), encoding="utf-8")

    # ── tiap bar M5 baru ────────────────────────────────────────────────────
    def on_bar(self) -> None:
        df = self.ex.rates_df("M5", settings.PRO_BARS)
        bar_t = df.index[-1]
        if bar_t == self.last_bar:
            return
        self.last_bar = bar_t
        tick = self.ex.tick()
        # bar "sedang berjalan" sintetis: open = harga sekarang → dipakai simulasi untuk entry market
        nxt = pd.DataFrame({"open": [tick.bid], "high": [tick.bid], "low": [tick.bid], "close": [tick.bid],
                            "spread": [tick.spread]}, index=[bar_t + pd.Timedelta(minutes=5)])
        df = pd.concat([df, nxt])
        events = high_impact_times() if settings.PRO_NEWS_MIN > 0 else []
        block = news_block(df.index, events, settings.PRO_NEWS_MIN)
        now = datetime.now(timezone.utc)
        in_news = any(abs((now - e).total_seconds()) <= settings.PRO_NEWS_MIN * 60 for e in events)

        self.sync(df, in_news)
        mk = ps.Market(df, EMA_SPAN, BIAS_TF, MIN_SLOPE)
        finals = {}
        for is_buy in (True, False):
            d = "BUY" if is_buy else "SELL"
            final: dict = {}
            ps.run_side(mk, CFG, is_buy, block, final)
            finals[is_buy] = final
            st, s, last_i = final["state"], final["s"], final["last_i"]
            if st == "armed" and s["arm_i"] == last_i:
                p = s["poi"]
                sg = 1 if is_buy else -1
                lo, hi = sorted((sg * p[2], sg * p[3]))
                log.info("%s ARMED: harga menyentuh POI M15 %s %.2f–%.2f (bias EMA50 H1 searah), "
                         "tunggu CHoCH M5", d, p[4], lo, hi)
            for k, lvl, ci, p in final.get("chochs", []):
                if ci == last_i:
                    sg = 1 if is_buy else -1
                    log.info("%s CHoCH M5: close %s %s %.2f (swing %s WIB) · POI M15 %s", d,
                             "di atas" if is_buy else "di bawah", "swing high" if is_buy else "swing low",
                             sg * lvl, (pd.Timestamp(mk.t[k]) + pd.Timedelta(hours=7)).strftime("%d/%m %H:%M"),
                             p[4])
            if d in self.state["live"]:
                continue
            self.maybe_order(d, is_buy, mk, st, s, last_i, in_news, tick)
        self.save()
        try:
            self.export_markers(mk, finals, tick)
        except Exception:
            log.exception("gagal menulis marker POI")

    def export_markers(self, mk: ps.Market, finals: dict, tick) -> None:
        """Tulis POI M15 aktif, POI armed, CHoCH M5, dan order ke Common\\Files\\pro_poi.csv untuk indikator
        ProPOI (MT5). Format per baris (8 kolom): rec,dir,kind,t1(epoch jam server),p1,p2,p3,flag.
        CHOCH: t1 = waktu swing, p1 = level, p2 = epoch bar break (kind 'wait': bar terakhir),
        flag 1 = CHoCH sudah terjadi, 0 = level yang ditunggu saat POI armed."""
        i = mk.n - 2                                    # bar M5 terakhir yang sudah close
        off = int(settings.MT5_UTC_OFFSET_H * 3600)
        epoch = lambda k: int(mk.t[k].astype("datetime64[s]").astype(np.int64)) + off
        px = tick.bid
        rows = [f"HDR,,,{int(time.time()) + off},0,0,0,0"]
        for is_buy in (True, False):
            d, sg = ("BUY", 1) if is_buy else ("SELL", -1)
            bias = int(bool(mk.bias[("ema", is_buy)][i]))
            for created, dead, top, bottom, kind in mk.pois[is_buy]:
                if not (created < i <= dead and i - created <= ps.POI_AGE):
                    continue
                lo, hi = sorted((sg * top, sg * bottom))
                if abs((lo + hi) / 2 - px) > 25:        # cukup yang dekat harga
                    continue
                rows.append(f"POI,{d},{kind},{epoch(created)},{lo:.2f},{hi:.2f},0,{bias}")
            f = finals.get(is_buy, {})
            if f.get("state") == "armed":
                p = f["s"]["poi"]
                lo, hi = sorted((sg * p[2], sg * p[3]))
                rows.append(f"ARMED,{d},{p[4]},{epoch(f['s']['arm_i'])},{lo:.2f},{hi:.2f},0,1")
                if "ch_k" in f["s"]:                    # level CHoCH yang ditunggu (garis putus)
                    rows.append(f"CHOCH,{d},wait,{epoch(f['s']['ch_k'])},{sg * f['s']['ch_lvl']:.2f},"
                                f"{epoch(i)},0,0")
            # CHoCH M5 yang sudah terjadi (24 jam terakhir, dekat harga): garis swing → bar break
            recent = [c for c in f.get("chochs", []) if c[2] >= i - CHOCH_SHOW_BARS
                      and abs(sg * c[1] - px) <= 40][-CHOCH_SHOW_MAX:]
            for k, lvl, ci, p in recent:
                rows.append(f"CHOCH,{d},{p[4]},{epoch(k)},{sg * lvl:.2f},{epoch(ci)},0,1")
            rec = self.state["live"].get(d)
            if rec:
                t = int(pd.Timestamp(rec["placed"]).timestamp()) + off
                rows.append(f"ORDER,{d},{rec['kind']},{t},{rec['price']:.2f},{rec['sl']:.2f},{rec['tp']:.2f},1")
        path = self.ex.common_files_dir() / "pro_poi.csv"
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(rows) + "\n", encoding="ascii")
        tmp.replace(path)

    def maybe_order(self, d, is_buy, mk, st, s, last_i, in_news, tick) -> None:
        sg = 1 if is_buy else -1
        if st == "pending":
            created = s["pend_until"] - ps.PEND_WAIT
            if created != last_i:
                return
            kind, price = "LIMIT", sg * s["lim"]
        elif st == "open" and not s.get("limit") and s["entry_i"] == mk.n - 1:
            kind, price = "MARKET", tick.ask if is_buy else tick.bid
        else:
            return
        key = f"{d}-{pd.Timestamp(mk.t[s['arm_i']]).isoformat()}"
        if key in self.state["used"]:
            return
        self.state["used"].append(key)
        sl = sg * s["sl0"]
        risk = abs(price - sl)
        tp = price + sg * CFG.rr * risk
        p = s["poi"]
        info = (f"{d} {kind} @ {price:.2f} SL {sl:.2f} TP {tp:.2f} (risiko {risk / settings.PIP_SIZE:.0f} pips) "
                f"| POI M15 {p[4]}")
        if in_news or settings.is_paused(settings.PAUSE_PRO):
            log.info("SETUP DILEWATI (%s): %s", "news" if in_news else "PAUSE", info)
            return
        # pending yang harganya sudah terlewati → market (simulasi juga akan terisi di open berikutnya)
        if kind == "LIMIT" and sg * ((tick.ask if is_buy else tick.bid) - price) <= 0:
            kind, price = "MARKET", tick.ask if is_buy else tick.bid
            risk = abs(price - sl)
            tp = price + sg * CFG.rr * risk
        if not (ps.RISK_MIN <= risk <= ps.RISK_MAX):
            log.info("SETUP DILEWATI (risiko %.0f pips di luar 10–100): %s", risk / settings.PIP_SIZE, info)
            return
        rec = {"key": key, "kind": "pending" if kind == "LIMIT" else "position", "dir": d, "price": price,
               "sl": sl, "tp": tp, "risk": risk, "poi": p[4], "placed": datetime.now(timezone.utc).isoformat(),
               "bars": 0, "ticket": None}
        if self.mode == "DEMO":
            try:
                if kind == "LIMIT":
                    rec["ticket"] = self.ex.place_limit(d, settings.PRO_LOT, price, sl, tp, comment="pro")
                else:
                    f = self.ex.open_market_at(d, settings.PRO_LOT, sl, tp, comment="pro")
                    rec.update(ticket=f.ticket, price=f.price)
            except RuntimeError as e:
                log.error("ORDER GAGAL %s: %s", info, e)
                return
        self.state["live"][d] = rec
        log.info("ORDER %s %s (ticket %s)", self.mode, info, rec["ticket"] or "paper")

    # ── pantau order yang sudah dikirim ─────────────────────────────────────
    def sync(self, df: pd.DataFrame, in_news: bool) -> None:
        last = df.iloc[-2]                              # bar M5 terakhir yang sudah close
        for d, rec in list(self.state["live"].items()):
            sg = 1 if d == "BUY" else -1
            if rec["kind"] == "pending":
                rec["bars"] += 1
                filled = self._filled(rec, last)
                if filled is None:
                    continue
                if filled:
                    rec["kind"] = "position"
                    log.info("PENDING TERISI %s @ %.2f (ticket %s)", d, rec["price"], rec["ticket"] or "paper")
                    continue
                hit_tp = sg * ((last["high"] if sg == 1 else last["low"]) - rec["tp"]) >= 0
                why = ("jendela news" if in_news else "harga sampai TP sebelum terisi" if hit_tp
                       else "12 bar tanpa fill" if rec["bars"] >= ps.PEND_WAIT else None)
                if why:
                    if self.mode == "DEMO" and not self.ex.cancel_order(rec["ticket"]):
                        log.error("gagal membatalkan pending %s", rec["ticket"])
                        continue
                    log.info("PENDING %s @ %.2f dibatalkan: %s", d, rec["price"], why)
                    del self.state["live"][d]
                continue
            self._check_closed(d, rec, last)

    def _filled(self, rec, last) -> bool | None:
        """True terisi · False masih pending · None = order hilang (dicatat & dihapus)."""
        if self.mode != "DEMO":
            hit = last["low"] + last["spread"] <= rec["price"] if rec["dir"] == "BUY" else last["high"] >= rec["price"]
            return bool(hit)
        if rec["ticket"] in self.ex.pending_tickets():
            return False
        if self.ex.position_of(rec["ticket"]) or self.ex.entry_deal(rec["ticket"]):
            return True
        log.warning("pending %s hilang dari MT5 (dibatalkan manual?)", rec["ticket"])
        del self.state["live"][rec["dir"]]
        return None

    def _check_closed(self, d, rec, last) -> None:
        if self.mode == "DEMO":
            if rec["ticket"] in self.ex.open_tickets():
                return
            c = self.ex.closed_info(rec["ticket"])
            if c is None:
                return
            exit_px, usd, why, when = c.exit_price, c.profit_usd, c.reason, c.time
        else:
            sg = 1 if d == "BUY" else -1
            lo, hi = (last["low"], last["high"]) if sg == 1 else (-last["high"] - last["spread"],
                                                                 -last["low"] - last["spread"])
            if lo <= sg * rec["sl"]:
                exit_px, why = rec["sl"], "SL"
            elif hi >= sg * rec["tp"]:
                exit_px, why = rec["tp"], "TP"
            else:
                return
            usd = round(sg * (exit_px - rec["price"]) / settings.PIP_SIZE * settings.USD_PER_PIP_001
                        * settings.PRO_LOT / 0.01, 2)
            when = datetime.now(timezone.utc)
        r = round((1 if d == "BUY" else -1) * (exit_px - rec["price"]) / rec["risk"], 2)
        log.info("TUTUP %s %s → %s %+.2fR (%+.2f USD) | entry %.2f exit %.2f", rec["ticket"] or "paper", d, why,
                 r, usd, rec["price"], exit_px)
        new = not TRADES_PATH.exists()
        with TRADES_PATH.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["mode", "ticket", "dir", "placed", "closed", "entry", "sl", "tp", "exit", "R", "usd",
                            "outcome", "poi"])
            w.writerow([self.mode, rec["ticket"], d, rec["placed"], when, rec["price"], rec["sl"], rec["tp"],
                        exit_px, r, usd, why, rec["poi"]])
        del self.state["live"][d]


def main() -> None:
    ap = argparse.ArgumentParser(description="Runner live strategi sendiri (akun demo)")
    ap.add_argument("--mode", default="DEMO", choices=("LOG", "DEMO"))
    args = ap.parse_args()
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(settings.DATA_DIR / "pro_live.log", encoding="utf-8")])
    ex = MT5Executor(magic=settings.PRO_MAGIC)
    ex.connect()
    st = ex.status()
    if args.mode == "DEMO" and not st["algo_trading"]:
        raise SystemExit("Tombol 'Algo Trading' di MT5 masih MATI — nyalakan dulu.")
    log.info("PRO %s login %s (demo=%s) saldo %.2f | %s bias EMA%d H1 slope>%g ATR | lot %s | magic %s | news ±%g mnt",
             args.mode, st["login"], st["demo"], st["balance"], CFG.name, EMA_SPAN, MIN_SLOPE, settings.PRO_LOT,
             settings.PRO_MAGIC, settings.PRO_NEWS_MIN)
    trader = ProTrader(ex, args.mode)
    try:
        while True:
            HEARTBEAT.touch()
            try:
                trader.on_bar()
            except Exception:
                log.exception("siklus gagal")
            time.sleep(LOOP_SEC)
    finally:
        ex.shutdown()


if __name__ == "__main__":
    main()
