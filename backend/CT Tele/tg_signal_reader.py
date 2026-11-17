# -*- coding: utf-8 -*-
"""
TG Signal Reader -> MT4  (v1.1)
Membaca sinyal dari grup Telegram, lalu menulisnya ke file yang dibaca
EA "TG_Signal_Layer" di MT4.

Pemakaian (di Command Prompt, dari folder script ini):
  python tg_signal_reader.py --list            tampilkan daftar grup + ID-nya
  python tg_signal_reader.py --test "BUY 71-67"  uji pembacaan sinyal (tanpa Telegram)
  python tg_signal_reader.py --history 3       ekspor sinyal 3 hari terakhir (untuk backtest)
  python tg_signal_reader.py                   jalankan pembaca sinyal
"""

# ====================== PENGATURAN (WAJIB DIISI) ======================
API_ID = 1234567                 # dari my.telegram.org
API_HASH = "isi_api_hash_anda"   # dari my.telegram.org
CHAT_ID = -1002803574839                      # Smart Risk Indonesia (SRI), dari hasil --list
# ======================================================================

POLL_SEC = 15                    # cek cadangan tiap 15 detik
SESSION_NAME = "tg_signal"       # nama file sesi login (tg_signal.session)
FILE_NAME = "tg_signals.txt"     # harus sama dengan input SignalFile di EA
OUTPUT_FILE = ""                 # kosongkan = otomatis ke folder Common\Files MT4

import os
import re
import sys
import logging
import time
import csv
from datetime import datetime, timedelta, timezone

# Supaya emoji di nama grup/pesan tidak bikin error di Command Prompt
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.FileHandler("tg_reader.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("tg")


def output_path():
    if OUTPUT_FILE:
        return OUTPUT_FILE
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    folder = os.path.join(appdata, "MetaQuotes", "Terminal", "Common", "Files")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, FILE_NAME)


# ---------------------------- PARSER SINYAL ----------------------------
NUM = r"(\d{1,4}(?:[.,]\d{1,2})?)"
PREFIX = r"^\W*(?:XAU\w*|GOLD)?\W*"
# "BUY 71-67", "SELL 37 - 41", "🟢 BUY 4071-4067", "GOLD SELL 15-19"
RE_ZONE = re.compile(PREFIX + r"(BUY|SELL)\b\W*(?:LIMIT|ZONE|AREA|AT)?\W*" + NUM
                     + r"\s*[-–—~]\s*" + NUM + r"(?!\d)", re.I)
# "Buy Now", "SELL NOW", "Sell sekarang"
RE_NOW = re.compile(PREFIX + r"(BUY|SELL)\W*(?:NOW|SEKARANG)\b", re.I)
# "SL 30 pips"
RE_SL = re.compile(r"\bSL\b\W*(\d{1,3}(?:[.,]\d)?)\s*pips?\b", re.I)
# Baris pertama yang berisi kata ini = update/rekap, BUKAN sinyal baru
RE_BLOCK = re.compile(r"✅|❌|✔|☑|\bHIT\b|\bCLOSE\b|\bREPORT\b|\bREKAP\b|\bRECAP\b"
                      r"|\bRUNNING\b|\bBEP\b|\bDONE\b|\bCUT\b", re.I)


def _num(s):
    return float(s.replace(",", "."))


def parse_signal(text):
    """Kembalikan dict sinyal, atau None kalau pesan bukan sinyal baru."""
    if not text:
        return None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return None
    first = lines[0]
    if RE_BLOCK.search(first):
        return None

    m_sl = RE_SL.search(text)
    sl = _num(m_sl.group(1)) if m_sl else 0  # 0 = EA pakai SL default

    m = RE_NOW.match(first)
    if m:
        return {"type": "NOW", "side": m.group(1).upper(), "a": 0, "b": 0, "sl": sl}

    m = RE_ZONE.match(first)
    if m:
        a, b = _num(m.group(2)), _num(m.group(3))
        if a == b:
            return None
        return {"type": "ZONE", "side": m.group(1).upper(), "a": a, "b": b, "sl": sl}
    return None


def write_signal(msg_id, ts, sig):
    line = "{};{};{};{};{:g};{:g};{:g};END\n".format(
        msg_id, ts, sig["type"], sig["side"], sig["a"], sig["b"], sig["sl"])
    with open(output_path(), "a", encoding="ascii") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    return line.strip()


# ------------------------------ TELEGRAM -------------------------------
async def list_chats(client):
    print("\n{:>16}  {}".format("ID", "NAMA GRUP / CHANNEL"))
    async for d in client.iter_dialogs():
        if d.is_group or d.is_channel:
            print("{:>16}  {}".format(d.id, d.name))
    print("\nSalin ID grup sinyal ke CHAT_ID di bagian atas script.")


async def export_history(client, days):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = []
    async for m in client.iter_messages(CHAT_ID, offset_date=since, reverse=True):
        text = m.raw_text or ""
        sig = parse_signal(text)
        if sig:
            rows.append([m.id, int(m.date.timestamp()), sig["type"], sig["side"],
                         sig["a"], sig["b"], sig["sl"], text.splitlines()[0][:60]])
    with open("signals_history.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "time_utc", "type", "side", "a", "b", "sl", "text"])
        w.writerows(rows)
    print("{} sinyal ditulis ke signals_history.csv".format(len(rows)))


def main():
    args = sys.argv[1:]

    if args[:1] == ["--test"]:
        text = " ".join(args[1:]).replace("\\n", "\n")
        print(parse_signal(text))
        return

    from telethon import TelegramClient, events

    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    if args[:1] == ["--list"]:
        with client:  # login pertama kali: minta nomor HP + kode OTP
            client.loop.run_until_complete(list_chats(client))
        return

    if not CHAT_ID:
        print("CHAT_ID belum diisi. Jalankan dulu: python tg_signal_reader.py --list")
        return

    if args[:1] == ["--history"]:
        days = int(args[1]) if len(args) > 1 else 1
        with client:
            client.loop.run_until_complete(export_history(client, days))
        return

    import asyncio
    seen = set()
    state = {"last_id": 0, "last_msg": time.time()}

    def handle(msg, via):
        if msg.id in seen:
            return
        seen.add(msg.id)
        state["last_id"] = max(state["last_id"], msg.id)
        state["last_msg"] = time.time()
        text = msg.raw_text or ""
        preview = text.splitlines()[0][:60] if text.strip() else "(bukan teks)"
        sig = parse_signal(text)
        if not sig:
            log.info("abaikan   | %s", preview)
            return
        ts = int(msg.date.timestamp())
        line = write_signal(msg.id, ts, sig)
        log.info("SINYAL %s| %s  ->  %s", via, preview, line)

    @client.on(events.NewMessage(chats=CHAT_ID))
    async def on_message(event):
        handle(event.message, "   ")

    async def poller():
        # Cadangan: cek grup setiap POLL_SEC detik, kalau push dari Telegram tidak sampai
        n = 0
        while True:
            await asyncio.sleep(POLL_SEC)
            try:
                msgs = await client.get_messages(CHAT_ID, limit=10)
                for m in sorted(msgs, key=lambda x: x.id):
                    if m.id > state["last_id"]:
                        handle(m, "(p)")
            except Exception as e:
                log.info("poll gagal: %s", e)
            n += 1
            if n % max(1, 1800 // POLL_SEC) == 0:
                mnt = int((time.time() - state["last_msg"]) / 60)
                log.info("masih aktif | pesan terakhir id %s, %s menit lalu", state["last_id"], mnt)

    async def start():
        entity = await client.get_entity(CHAT_ID)
        name = getattr(entity, "title", CHAT_ID)
        last = await client.get_messages(CHAT_ID, limit=1)
        if last:
            state["last_id"] = last[0].id
            seen.add(last[0].id)
        log.info("Memantau grup: %s | pesan terakhir id %s", name, state["last_id"])
        client.loop.create_task(poller())

    with client:
        log.info("Pembaca sinyal aktif. File output: %s", output_path())
        client.loop.run_until_complete(start())
        client.run_until_disconnected()

if __name__ == "__main__":
    main()
