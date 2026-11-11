"""
Program live: dengar topik Scalping → parse sinyal → entry market di akun DEMO.

    python -m tg_signal.run_live --mode DEMO     # order sungguhan di akun demo
    python -m tg_signal.run_live --mode LOG      # hanya catat (paper), tanpa order

Aturan (settings.py, bisa di-override via .env):
- Entry market saat sinyal baru diterima (bukan pesan edit), 1 sinyal = 1 posisi, tanpa layering.
- Lot TG_LOT, TP TG_TP_PIPS, SL TG_SL_PIPS dari entry (TG_SL_FROM).
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
from tg_signal.executor import MT5Executor
from tg_signal.ingest import ingest_message
from tg_signal.price_resolver import resolve_zone
from tg_signal.risk import RiskLimits, RiskState, check
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
        daily_loss_usd=settings.TG_DAILY_LOSS_USD,
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
        self.store.add_trade(sid, self.mode, ticket, sig["direction"], settings.TG_LOT, t_open, entry, sl, tp)
        self.store.set_status(sid, "OPEN", f"ticket {ticket}" if ticket else "paper")
        log.info("sinyal #%s %s | %s %s @ %.3f SL %.3f TP %.3f (ticket %s)", msg_id, desc, self.mode,
                 sig["direction"], entry, sl, tp, ticket)

    def sync(self) -> None:
        """Tandai trade yang sudah tutup (TP/SL) dan catat hasilnya."""
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
    log.info("MT5 %s login %s (demo=%s) saldo %.2f %s | mode %s | TP %s pips, SL %s pips dari %s, "
             "lot %s, maks posisi %s", st["server"], st["login"], st["demo"], st["balance"], st["currency"],
             mode, settings.TG_TP_PIPS, settings.TG_SL_PIPS, settings.TG_SL_FROM, settings.TG_LOT,
             settings.TG_MAX_POSITIONS)
    trader = LiveTrader(store, ex, mode)

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
