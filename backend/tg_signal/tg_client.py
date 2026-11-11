"""
Telethon client — HANYA MEMBACA grup sinyal (RULES §6).

Login pertama kali akan meminta nomor HP + kode OTP di terminal;
session disimpan di tg_signal/data/ (gitignored, jangan dibagikan).

    python -m tg_signal.tg_client --list-groups          # cari nama/ID grup
    python -m tg_signal.tg_client --dump-history         # ambil seluruh riwayat → SQLite
    python -m tg_signal.tg_client --dump-history --limit 500
    python -m tg_signal.tg_client --listen               # pesan baru & edit, real-time
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from telethon import TelegramClient, events

from tg_signal import settings
from tg_signal.ingest import ingest_message
from tg_signal.store import Store


def _make_client() -> TelegramClient:
    if not settings.TG_API_ID or not settings.TG_API_HASH:
        sys.exit("TG_API_ID / TG_API_HASH belum diisi di backend/.env")
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return TelegramClient(str(settings.SESSION_PATH), int(settings.TG_API_ID), settings.TG_API_HASH)


def _group_ref() -> str | int:
    g = settings.TG_GROUP.strip()
    if not g:
        sys.exit("TG_GROUP belum diisi di backend/.env (jalankan --list-groups untuk mencari)")
    return int(g) if g.lstrip("-").isdigit() else g


async def list_groups(client: TelegramClient) -> None:
    async for d in client.iter_dialogs():
        if d.is_group or d.is_channel:
            print(f"{d.id:>16}  {d.name}")


async def dump_history(client: TelegramClient, store: Store, limit: int | None) -> None:
    entity = await client.get_entity(_group_ref())
    counts: dict[str, int] = {}
    n = 0
    async for msg in client.iter_messages(entity, limit=limit, reverse=limit is None):
        kind = ingest_message(store, entity.id, msg.id, msg.date, msg.message or "",
                              msg.edit_date, settings.TG_DEFAULT_SL_PIPS)
        counts[kind] = counts.get(kind, 0) + 1
        n += 1
        if n % 500 == 0:
            print(f"  ... {n} pesan")
    print(f"Selesai: {n} pesan diproses → {counts}")


async def listen(client: TelegramClient, store: Store) -> None:
    entity = await client.get_entity(_group_ref())

    async def handle(event) -> None:
        msg = event.message
        kind = ingest_message(store, entity.id, msg.id, msg.date, msg.message or "",
                              msg.edit_date, settings.TG_DEFAULT_SL_PIPS)
        first = (msg.message or "").splitlines()[0][:60] if msg.message else ""
        print(f"[{msg.date:%H:%M:%S}] {kind:<9} #{msg.id} {first}")

    client.add_event_handler(handle, events.NewMessage(chats=entity))
    client.add_event_handler(handle, events.MessageEdited(chats=entity))
    print(f"Mendengarkan grup {entity.id} ... (Ctrl+C untuk berhenti)")
    await client.run_until_disconnected()


async def _run(args: argparse.Namespace) -> None:
    client = _make_client()
    await client.start()
    store = Store(settings.DB_PATH)
    try:
        if args.list_groups:
            await list_groups(client)
        elif args.dump_history:
            await dump_history(client, store, args.limit)
        elif args.listen:
            await listen(client, store)
    finally:
        store.close()
        await client.disconnect()


def main() -> None:
    ap = argparse.ArgumentParser(description="Telegram reader untuk tg_signal")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list-groups", action="store_true")
    g.add_argument("--dump-history", action="store_true")
    g.add_argument("--listen", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="hanya N pesan terbaru")
    asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    main()
