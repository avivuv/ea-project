"""
Program live: dengar topik Scalping → parse sinyal → entry market di akun DEMO.

    python -m tg_signal.run_live --mode DEMO     # order sungguhan di akun demo
    python -m tg_signal.run_live --mode LOG      # hanya catat (paper), tanpa order

Aturan (settings.py, bisa di-override via .env):
- TG_ENTRY_MODE=MARKET (default): entry market saat sinyal diterima, SL TG_SL_PIPS dari entry (TG_SL_FROM).
- TG_ENTRY_MODE=ZONE (opsional): harga sudah di zona → market; belum → pending limit di ZERO.
  SL = LAST ∓ TG_SL_PIPS, TP = entry ± TG_TP_PIPS. Pending hangus bila harga sampai ZERO ± TP tanpa
  fill; sinyal baru menggantikan pending lama. Lihat entry_plan.py.
- Hanya pesan baru (bukan edit), 1 sinyal = 1 posisi, tanpa layering, lot TG_LOT.
- Risk check: lihat risk.py. Kill switch: buat file tg_signal/data/PAUSE.
- Akun non-demo ditolak oleh executor.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from telethon import errors, events

from tg_signal import settings
from tg_signal.detectors.poi import zone_pois
from tg_signal.entry_plan import limit_filled, pending_expired, plan_entry, plan_poi
from tg_signal.executor import MT5Executor
from tg_signal.ingest import ingest_message
from tg_signal.price_resolver import resolve_zone
from tg_signal.risk import RiskLimits, RiskState, check, target_hit
from tg_signal.store import Store
from tg_signal.tg_client import _group_ref, _make_client, _sender_name, in_topic

log = logging.getLogger("tg_signal.live")
PIP = settings.PIP_SIZE
SYNC_EVERY_SEC = 5


def day_start_utc(now: datetime) -> datetime:
    local = now + timedelta(hours=settings.TG_DAY_TZ_HOURS)
    return datetime(local.year, local.month, local.day, tzinfo=timezone.utc) - timedelta(hours=settings.TG_DAY_TZ_HOURS)


def limits() -> RiskLimits:
    return RiskLimits(
        max_zone_distance=settings.TG_MAX_ZONE_DISTANCE, max_spread_pips=settings.TG_MAX_SPREAD_PIPS,
        max_positions=settings.TG_MAX_POSITIONS, max_trades_day=settings.TG_MAX_TRADES_DAY,
        daily_loss_usd=settings.TG_DAILY_LOSS_USD, daily_profit_usd=settings.TG_DAILY_PROFIT_USD,
    )


class LiveTrader:
    def __init__(self, store: Store, ex: MT5Executor, mode: str):
        self.store, self.ex, self.mode = store, ex, mode

    def handle_signal(self, chat_id: int, msg_id: int) -> None:
        sig = self.store.signal_for_message(chat_id, msg_id)
        if sig is None or sig["status"] != "NEW":
            return
        sid = sig["id"]
        if self.store.recent_duplicate(sig, settings.TG_DUPLICATE_WINDOW_SEC):
            self.store.set_status(sid, "REJECTED", "DUPLICATE")
            log.info("sinyal #%s %s %02d-%02d → duplikat, diabaikan", msg_id, sig["direction"],
                     sig["level_first"], sig["level_last"])
            return

        tick = self.ex.tick()
        ref = tick.bid
        zone = resolve_zone(sig["direction"], sig["level_first"], sig["level_last"], ref,
                            settings.TG_ZONE_WIDTH_MIN, settings.TG_ZONE_WIDTH_MAX)
        self.store.set_zone(sid, ref, zone.zero, zone.last, zone.flags)

        now = datetime.now(timezone.utc)
        n_today, pnl_today = self.store.day_stats(day_start_utc(now), self.mode)
        opens = [(t["direction"], 0.0) for t in self.store.open_trades(self.mode)]
        st = RiskState(spread_pips=tick.spread / PIP, open_positions=opens, trades_today=n_today,
                       pnl_today_usd=pnl_today, paused=settings.PAUSE_FILE.exists(), price_age_sec=tick.age_sec)
        ok, reason = check(sig["direction"], zone.zero, zone.distance, st, limits())
        desc = f"{sig['direction']} {sig['level_first']:02d}-{sig['level_last']:02d} → zona {zone.zero:.0f}/{zone.last:.0f}"
        if not ok:
            self.store.set_status(sid, "REJECTED", reason)
            log.info("sinyal #%s %s | DITOLAK: %s (spread %.1f pips)", msg_id, desc, reason, st.spread_pips)
            return

        sl_dist = settings.TG_SL_PIPS * PIP
        tp_dist = settings.TG_TP_PIPS * PIP
        if settings.TG_ENTRY_MODE == "POI":
            self._cancel_pendings(f"diganti sinyal #{msg_id}")      # sinyal terbaru menggantikan pending lama
            pois = self._zone_pois(sig["direction"], zone.zero, zone.last)
            plan = plan_poi(sig["direction"], zone.zero, zone.last, tick.bid, tick.ask, pois, sl_dist, tp_dist)
            log.info("sinyal #%s %s | POI di zona: %s", msg_id, desc,
                     ", ".join(f"{k} {min(a, b):.2f}-{max(a, b):.2f}" for a, b, k in pois) or "tidak ada")
            if plan.kind == "REJECT":
                self.store.set_status(sid, "REJECTED", plan.reason)
                log.info("sinyal #%s %s | DITOLAK: %s", msg_id, desc, plan.reason)
                return
            if plan.kind == "LIMIT":
                self._place_pending(sid, msg_id, sig["direction"], plan, f"{desc} | {plan.reason}")
                return
            self._open_market(sid, msg_id, sig["direction"], desc, sl=plan.sl, tp=plan.tp, tick=tick)
            return

        if settings.TG_ENTRY_MODE == "ZONE":
            self._cancel_pendings(f"diganti sinyal #{msg_id}")      # sinyal terbaru menggantikan pending lama
            plan = plan_entry(sig["direction"], zone.zero, zone.last, tick.bid, tick.ask, sl_dist, tp_dist)
            if plan.kind == "REJECT":
                self.store.set_status(sid, "REJECTED", plan.reason)
                log.info("sinyal #%s %s | DITOLAK: %s", msg_id, desc, plan.reason)
                return
            if plan.kind == "LIMIT":
                self._place_pending(sid, msg_id, sig["direction"], plan, desc)
                return
            self._open_market(sid, msg_id, sig["direction"], desc, sl=plan.sl, tp=plan.tp, tick=tick)
            return

        if self.mode == "DEMO":
            try:
                fill = self.ex.open_market(sig["direction"], settings.TG_LOT, sl_dist, tp_dist,
                                           zone.last, settings.TG_SL_FROM, comment=f"tg{msg_id}")
            except RuntimeError as e:
                self.store.set_status(sid, "REJECTED", f"ORDER_FAILED: {e}")
                log.error("sinyal #%s %s | ORDER GAGAL: %s", msg_id, desc, e)
                return
            ticket, entry, sl, tp, t_open = fill.ticket, fill.price, fill.sl, fill.tp, fill.time
        else:   # LOG: posisi kertas di harga saat ini
            g = 1 if sig["direction"] == "BUY" else -1
            entry = tick.ask if g == 1 else tick.bid
            ticket, sl, tp, t_open = None, entry - g * sl_dist, entry + g * tp_dist, now
        self._record_open(sid, msg_id, sig["direction"], desc, ticket, t_open, entry, sl, tp)

    # ── mode POI ────────────────────────────────────────────────────────────
    def _zone_pois(self, direction, zero, last) -> list[tuple[float, float, str]]:
        """POI (FVG/OB/IFVG) di dalam zona dari bar TG_POI_TF yang sudah close. Gagal ambil bar → []."""
        try:
            _, o, h, l, c = self.ex.rates(settings.TG_POI_TF, settings.TG_POI_BARS)
        except RuntimeError as e:
            log.warning("gagal ambil bar %s untuk POI: %s", settings.TG_POI_TF, e)
            return []
        return zone_pois(direction, o, h, l, c, zero, last, settings.TG_POI_TOL,
                         settings.TG_POI_MAX_AGE, settings.TG_POI_MIN_SIZE)

    def _reprice_pendings(self, pendings, tick) -> None:
        """Tiap bar baru: batalkan pending yang sinyalnya gagal (lewat LAST ∓ SL) dan pindahkan limit ke POI
        terdekat yang masih valid (POI lama gagal / muncul POI baru yang lebih dekat)."""
        try:
            t, *_ = self.ex.rates(settings.TG_POI_TF, 1)
        except RuntimeError:
            return
        bar = int(t[-1])
        if bar == getattr(self, "_poi_bar", None):
            return
        self._poi_bar = bar
        sl_dist, tp_dist = settings.TG_SL_PIPS * PIP, settings.TG_TP_PIPS * PIP
        live_orders = self.ex.pending_tickets() if self.mode == "DEMO" else set()
        for p in pendings:
            d = p["direction"]
            if self.mode == "DEMO" and p["ticket"] not in live_orders:
                continue                            # sudah terisi / hilang → ditangani _sync_pendings
            pois = self._zone_pois(d, p["zero"], p["last"])
            plan = plan_poi(d, p["zero"], p["last"], tick.bid, tick.ask, pois, sl_dist, tp_dist, allow_market=False)
            if plan.kind == "REJECT":
                if self.mode == "DEMO" and not self.ex.cancel_order(p["ticket"]):
                    continue
                self.store.set_status(p["sid"], "EXPIRED", "harga melewati LAST − SL tanpa fill")
                log.info("pending %s %s @ %.2f hangus: harga sudah melewati LAST − SL", p["ticket"] or "paper",
                         d, p["price"])
                continue
            if plan.kind != "LIMIT" or abs(plan.price - p["price"]) < 0.05:
                continue
            ticket = None
            if self.mode == "DEMO":
                if not self.ex.cancel_order(p["ticket"]):
                    log.error("gagal membatalkan pending %s untuk dipindah", p["ticket"])
                    continue
                if self.ex.position_of(p["ticket"]) or self.ex.entry_deal(p["ticket"]):
                    continue                        # terisi tepat sebelum dibatalkan → sync berikutnya
                try:
                    ticket = self.ex.place_limit(d, settings.TG_LOT, plan.price, plan.sl, plan.tp,
                                                 comment=f"tgp{p['sid']}")
                except RuntimeError as e:
                    self.store.set_status(p["sid"], "CANCELLED", f"gagal pindah pending: {e}")
                    log.error("pending sinyal %s gagal dipindah: %s", p["sid"], e)
                    continue
            self.store.set_status(p["sid"], "PENDING", (f"order {ticket}" if ticket else "paper") +
                                  f" @ {plan.price:.2f}")
            log.info("pending %s %s dipindah %.2f → %.2f (%s) SL %.2f TP %.2f", ticket or "paper", d,
                     p["price"], plan.price, plan.reason, plan.sl, plan.tp)

    # ── mode ZONE ───────────────────────────────────────────────────────────
    def _open_market(self, sid, msg_id, direction, desc, sl, tp, tick) -> None:
        """Harga sudah di zona → entry market, SL/TP harga tetap dari rencana."""
        if self.mode == "DEMO":
            try:
                f = self.ex.open_market_at(direction, settings.TG_LOT, sl, tp, comment=f"tg{msg_id}")
            except RuntimeError as e:
                self.store.set_status(sid, "REJECTED", f"ORDER_FAILED: {e}")
                log.error("sinyal #%s %s | ORDER GAGAL: %s", msg_id, desc, e)
                return
            self._record_open(sid, msg_id, direction, desc + " | di zona → market", f.ticket, f.time,
                              f.price, f.sl, f.tp)
        else:
            entry = tick.ask if direction == "BUY" else tick.bid
            g = 1 if direction == "BUY" else -1
            self._record_open(sid, msg_id, direction, desc + " | di zona → market", None,
                              datetime.now(timezone.utc), entry, sl, entry + g * settings.TG_TP_PIPS * PIP)

    def _place_pending(self, sid, msg_id, direction, plan, desc) -> None:
        """Belum sampai zona → pending limit di ZERO."""
        ticket = None
        if self.mode == "DEMO":
            try:
                ticket = self.ex.place_limit(direction, settings.TG_LOT, plan.price, plan.sl, plan.tp,
                                             comment=f"tg{msg_id}")
            except RuntimeError as e:
                self.store.set_status(sid, "REJECTED", f"ORDER_FAILED: {e}")
                log.error("sinyal #%s %s | PENDING GAGAL: %s", msg_id, desc, e)
                return
        self.store.set_status(sid, "PENDING", (f"order {ticket}" if ticket else "paper") + f" @ {plan.price:.2f}")
        log.info("sinyal #%s %s | %s %s LIMIT @ %.2f SL %.2f TP %.2f (order %s)", msg_id, desc, self.mode,
                 direction, plan.price, plan.sl, plan.tp, ticket or "paper")

    def _pendings(self) -> list[dict]:
        """Pending aktif dari DB (bertahan saat program di-restart). Harga limit dari status ("... @ harga"),
        SL/TP dihitung ulang: mode POI dari harga limit, mode ZONE dari zona (SL = LAST ∓ SL)."""
        out = []
        sl_dist, tp_dist = settings.TG_SL_PIPS * PIP, settings.TG_TP_PIPS * PIP
        for s in self.store.signals("PENDING"):
            g = 1 if s["direction"] == "BUY" else -1
            reason = s["status_reason"]
            ticket = int(reason.split()[1]) if reason.startswith("order ") else None
            price = float(reason.rsplit("@", 1)[1]) if "@" in reason else s["zero"]
            if settings.TG_ENTRY_MODE == "POI":
                sl, tp = price - g * sl_dist, price + g * tp_dist
            else:
                sl, tp = s["last"] - g * sl_dist, s["zero"] + g * tp_dist
            out.append({"sid": s["id"], "direction": s["direction"], "ticket": ticket, "zero": s["zero"],
                        "last": s["last"], "price": price, "sl": sl, "tp": tp})
        return out

    def _cancel_pendings(self, reason: str) -> None:
        for p in self._pendings():
            if p["ticket"] is not None and self.mode == "DEMO":
                if p["ticket"] in self.ex.pending_tickets() and not self.ex.cancel_order(p["ticket"]):
                    log.error("gagal membatalkan pending %s", p["ticket"])
                    continue
                if self.ex.position_of(p["ticket"]) or self.ex.entry_deal(p["ticket"]):
                    continue        # ternyata sudah terisi → biar sync() yang mencatat
            self.store.set_status(p["sid"], "CANCELLED", reason)
            log.info("pending %s %s @ %.2f dibatalkan: %s", p["ticket"] or "paper", p["direction"], p["price"], reason)

    def _sync_pendings(self) -> None:
        pendings = self._pendings()
        if not pendings:
            return
        tick = self.ex.tick()
        if settings.TG_ENTRY_MODE == "POI":
            self._reprice_pendings(pendings, tick)
            pendings = self._pendings()
        live_orders = self.ex.pending_tickets() if self.mode == "DEMO" else set()
        for p in pendings:
            d, sid = p["direction"], p["sid"]
            if self.mode == "DEMO":
                if p["ticket"] in live_orders:
                    if pending_expired(d, p["zero"], tick.bid, tick.ask, settings.TG_TP_PIPS * PIP):
                        if self.ex.cancel_order(p["ticket"]):
                            self.store.set_status(sid, "EXPIRED", "TP tercapai tanpa fill")
                            log.info("pending %s %s @ %.2f hangus: harga sudah sampai TP tanpa fill",
                                     p["ticket"], d, p["zero"])
                    continue
                pos = self.ex.position_of(p["ticket"])
                if pos is not None:
                    self._record_fill(p, p["ticket"], pos.price_open, pos.sl, pos.tp,
                                      datetime.fromtimestamp(pos.time, timezone.utc))
                    continue
                deal = self.ex.entry_deal(p["ticket"])
                if deal is not None:    # terisi lalu langsung tutup di antara dua sync
                    self._record_fill(p, p["ticket"], deal.price, p["sl"], p["tp"],
                                      datetime.fromtimestamp(deal.time, timezone.utc))
                    continue
                self.store.set_status(sid, "CANCELLED", "order hilang dari MT5 (dibatalkan manual?)")
                log.warning("pending %s tidak ada lagi di MT5 dan tidak terisi", p["ticket"])
            else:
                if limit_filled(d, p["price"], tick.bid, tick.ask):
                    self._record_fill(p, None, p["price"], p["sl"], p["tp"], tick.time)
                elif pending_expired(d, p["zero"], tick.bid, tick.ask, settings.TG_TP_PIPS * PIP):
                    self.store.set_status(sid, "EXPIRED", "TP tercapai tanpa fill")
                    log.info("pending paper %s @ %.2f hangus: harga sudah sampai TP tanpa fill", d, p["zero"])

    def _record_fill(self, p, ticket, entry, sl, tp, when) -> None:
        self.store.add_trade(p["sid"], self.mode, ticket, p["direction"], settings.TG_LOT, when, entry, sl, tp)
        self.store.set_status(p["sid"], "OPEN", f"ticket {ticket}" if ticket else "paper")
        log.info("PENDING TERISI %s %s @ %.3f SL %.3f TP %.3f", ticket or "paper", p["direction"], entry, sl, tp)

    def _record_open(self, sid, msg_id, direction, desc, ticket, t_open, entry, sl, tp) -> None:
        self.store.add_trade(sid, self.mode, ticket, direction, settings.TG_LOT, t_open, entry, sl, tp)
        self.store.set_status(sid, "OPEN", f"ticket {ticket}" if ticket else "paper")
        log.info("sinyal #%s %s | %s %s @ %.3f SL %.3f TP %.3f (ticket %s)", msg_id, desc, self.mode,
                 direction, entry, sl, tp, ticket)

    def sync(self) -> None:
        """Pantau pending (terisi / hangus), lalu tandai trade yang sudah tutup (TP/SL)."""
        if settings.TG_ENTRY_MODE in ("ZONE", "POI"):
            self._sync_pendings()
        trades = self.store.open_trades(self.mode)
        if not trades:
            return
        if self.mode == "DEMO":
            still_open = self.ex.open_tickets()
            for t in trades:
                if t["ticket"] in still_open:
                    continue
                c = self.ex.closed_info(t["ticket"])
                if c is None:
                    continue
                self._close(t, c.time, c.exit_price, c.profit_usd, c.reason)
        else:
            tick = self.ex.tick()
            for t in trades:
                g = 1 if t["direction"] == "BUY" else -1
                px = tick.bid if g == 1 else tick.ask
                if g * (px - t["sl"]) <= 0:
                    self._close(t, tick.time, t["sl"], None, "SL")
                elif g * (px - t["tp"]) >= 0:
                    self._close(t, tick.time, t["tp"], None, "TP")
        self._check_daily_target()

    def _floating_usd(self, trades) -> float:
        if self.mode == "DEMO":
            return self.ex.floating_usd()
        tick = self.ex.tick()
        tot = 0.0
        for t in trades:
            g = 1 if t["direction"] == "BUY" else -1
            px = tick.bid if g == 1 else tick.ask
            tot += g * (px - t["entry"]) / PIP * settings.USD_PER_PIP_001 * t["lot"] / 0.01
        return round(tot, 2)

    def _check_daily_target(self) -> None:
        """Profit hari ini (tertutup + mengambang) ≥ target → tutup semua posisi & batalkan pending."""
        target = settings.TG_DAILY_PROFIT_USD
        trades = self.store.open_trades(self.mode)
        if target <= 0 or not trades:
            return
        _, realized = self.store.day_stats(day_start_utc(datetime.now(timezone.utc)), self.mode)
        floating = self._floating_usd(trades)
        if not target_hit(realized, floating, target):
            return
        log.info("TARGET HARIAN $%g tercapai (tertutup %+.2f + floating %+.2f) → tutup %d posisi",
                 target, realized, floating, len(trades))
        self._cancel_pendings("target profit harian tercapai")
        tick = self.ex.tick()
        for t in trades:
            g = 1 if t["direction"] == "BUY" else -1
            if self.mode == "DEMO":
                if not self.ex.close_position(t["ticket"]):
                    log.error("gagal menutup posisi %s — dicoba lagi di sync berikutnya", t["ticket"])
                    continue
                c = self.ex.closed_info(t["ticket"])
                if c is None:
                    continue            # deal belum muncul di history → sync berikutnya
                self._close(t, c.time, c.exit_price, c.profit_usd, "TARGET")
            else:
                self._close(t, tick.time, tick.bid if g == 1 else tick.ask, None, "TARGET")

    def _close(self, t, when, exit_price, profit, reason) -> None:
        g = 1 if t["direction"] == "BUY" else -1
        pips = g * (exit_price - t["entry"]) / PIP
        if profit is None:
            profit = round(pips * settings.USD_PER_PIP_001 * t["lot"] / 0.01, 2)
        self.store.close_trade(t["id"], when, exit_price, profit, pips, reason)
        self.store.set_status(t["signal_id"], "CLOSED", reason)
        n, pnl = self.store.day_stats(day_start_utc(datetime.now(timezone.utc)), self.mode)
        log.info("TUTUP %s %s → %s %+.1f pips (%+.2f USD) | hari ini: %d trade, %+.2f USD",
                 t["ticket"] or "paper", t["direction"], reason, pips, profit, n, pnl)


async def run(mode: str) -> None:
    store = Store(settings.DB_PATH)
    ex = MT5Executor()
    ex.connect()
    st = ex.status()
    if mode == "DEMO" and not st["algo_trading"]:
        raise SystemExit("Tombol 'Algo Trading' di MT5 masih MATI — nyalakan dulu, lalu jalankan ulang.")
    log.info("MT5 %s login %s (demo=%s) saldo %.2f %s | mode %s | entry %s | TP %s pips, SL %s pips dari %s, "
             "lot %s, maks posisi %s", st["server"], st["login"], st["demo"], st["balance"], st["currency"],
             mode, settings.TG_ENTRY_MODE, settings.TG_TP_PIPS, settings.TG_SL_PIPS,
             "LAST" if settings.TG_ENTRY_MODE == "ZONE" else settings.TG_SL_FROM, settings.TG_LOT,
             settings.TG_MAX_POSITIONS or "tanpa batas")
    trader = LiveTrader(store, ex, mode)
    if settings.TG_ENTRY_MODE == "MARKET":
        trader._cancel_pendings("mode entry kembali ke MARKET")    # buang pending sisa mode ZONE/POI

    client = _make_client()
    await client.start()
    entity = await client.get_entity(_group_ref())

    state = {"last_id": 0}
    latest = await client.get_messages(entity, limit=1, reply_to=settings.TG_TOPIC_ID or None)
    if latest:
        state["last_id"] = latest[0].id               # pesan lama tidak dieksekusi ulang

    def process(msg, via: str, is_edit: bool) -> None:
        """Satu jalur untuk push (event) dan polling. Sinkron → tidak ada balapan antar keduanya."""
        if not in_topic(msg, settings.TG_TOPIC_ID):
            return
        if not is_edit:
            if msg.id <= state["last_id"] and via == "poll":
                return
            state["last_id"] = max(state["last_id"], msg.id)
        kind = ingest_message(store, entity.id, msg.id, msg.date, msg.message or "", msg.edit_date,
                              settings.TG_DEFAULT_SL_PIPS, msg.sender_id, _sender_name(msg))
        if kind == "UNCHANGED":
            return
        lag = (datetime.now(timezone.utc) - msg.date).total_seconds()
        first = (msg.message or "").strip().splitlines()[0][:50] if msg.message else ""
        log.info("pesan #%s [%s] via %s, jeda %.0f dtk | %s", msg.id, kind, via, lag, first)
        if kind == "SIGNAL" and not is_edit:
            try:
                trader.handle_signal(entity.id, msg.id)
            except Exception:  # jangan sampai listener mati karena satu sinyal
                log.exception("gagal memproses sinyal #%s", msg.id)

    async def on_message(event) -> None:
        process(event.message, "push", isinstance(event, events.MessageEdited.Event))

    client.add_event_handler(on_message, events.NewMessage(chats=entity))
    client.add_event_handler(on_message, events.MessageEdited(chats=entity))

    async def poll_loop() -> None:
        """Telegram sering menunda push untuk grup besar (sampai ±60 dtk) → cek aktif tiap POLL_SEC."""
        while True:
            await asyncio.sleep(settings.TG_POLL_SEC)
            try:
                msgs = await client.get_messages(entity, limit=5, reply_to=settings.TG_TOPIC_ID or None)
                for m in sorted(msgs, key=lambda x: x.id):
                    process(m, "poll", False)
            except errors.FloodWaitError as e:
                log.warning("FloodWait %s dtk dari Telegram, polling dijeda", e.seconds)
                await asyncio.sleep(e.seconds + 1)
            except Exception:
                log.exception("polling gagal")

    asyncio.create_task(poll_loop())

    async def sync_loop() -> None:
        while True:
            try:
                trader.sync()
            except Exception:
                log.exception("sync gagal")
            await asyncio.sleep(SYNC_EVERY_SEC)

    asyncio.create_task(sync_loop())
    log.info("Mendengarkan topik %s di grup %s ... (Ctrl+C untuk berhenti)", settings.TG_TOPIC_ID, entity.id)
    try:
        await client.run_until_disconnected()
    finally:
        ex.shutdown()
        store.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Live trader sinyal Telegram (akun demo)")
    ap.add_argument("--mode", default=settings.TG_MODE, choices=("LOG", "DEMO"))
    args = ap.parse_args()
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(settings.DATA_DIR / "live.log", encoding="utf-8")],
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)
    asyncio.run(run(args.mode))


if __name__ == "__main__":
    main()
