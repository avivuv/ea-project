"""
Parameter modul tg_signal. Nilai bisa di-override via backend/.env.
Aturan lengkap: docs/scalping/RULES.md
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Output CLI selalu UTF-8 (Windows default cp1252 gagal mencetak →, ✅, ❌)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, default))


# ── Path ────────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = Path(os.getenv("TG_DB_PATH", DATA_DIR / "tg_signal.db"))
SESSION_PATH = DATA_DIR / "tg_session"          # Telethon menambah ".session"

# ── Telegram ────────────────────────────────────────────────────────────────
TG_API_ID = os.getenv("TG_API_ID", "")
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_GROUP = os.getenv("TG_GROUP", "")            # username, link, atau ID numerik
# Grup forum: hanya baca topik ini (topik "Scalping" = 1090). 0 = semua pesan grup.
TG_TOPIC_ID = int(os.getenv("TG_TOPIC_ID", "1090") or 0)

# ── Instrumen ───────────────────────────────────────────────────────────────
SYMBOL = os.getenv("TG_SYMBOL", "XAUUSD")
PIP_SIZE = 0.10                                 # 1 pip XAUUSD = $0.10 harga (keputusan D4)
USD_PER_PIP_001 = 0.10                          # 0.01 lot × 100 oz × $0.10
# Offset jam server MT5 terhadap UTC (Exness = 0). Bar MT5 dikonversi ke UTC.
MT5_UTC_OFFSET_H = _f("MT5_UTC_OFFSET_H", 0)
M1_CACHE_PATH = DATA_DIR / f"m1_{SYMBOL}.csv.gz"


def bars_cache_path(tf: str = "M1") -> Path:
    return DATA_DIR / f"{tf.lower()}_{SYMBOL}.csv.gz"

# ── Mode ────────────────────────────────────────────────────────────────────
TG_MODE = os.getenv("TG_MODE", "LOG").upper()   # LOG | DEMO | LIVE
TG_LIVE_CONFIRM = os.getenv("TG_LIVE_CONFIRM", "") == "YES"

# ── Sinyal ──────────────────────────────────────────────────────────────────
TG_DEFAULT_SL_PIPS = _f("TG_DEFAULT_SL_PIPS", 30)
TG_SL_PIPS = _f("TG_SL_PIPS", 30)
TG_EXPIRE_TP_PIPS = _f("TG_EXPIRE_TP_PIPS", 10)
TG_MAX_ZONE_DISTANCE = _f("TG_MAX_ZONE_DISTANCE", 15.0)   # dalam $ harga
TG_ZONE_WIDTH_MIN = _f("TG_ZONE_WIDTH_MIN", 1)
TG_ZONE_WIDTH_MAX = _f("TG_ZONE_WIDTH_MAX", 10)
TG_DUPLICATE_WINDOW_SEC = _i("TG_DUPLICATE_WINDOW_SEC", 300)

# ── Eksekusi (Tahap 4, akun demo) ───────────────────────────────────────────
TG_ENTRY_MODE = os.getenv("TG_ENTRY_MODE", "MARKET")    # entry market saat sinyal diterima
TG_TP_PIPS = _f("TG_TP_PIPS", 30)                       # TP = SL = 30 pips (keputusan user)
TG_SL_FROM = os.getenv("TG_SL_FROM", "entry")           # entry | zone (LAST − SL)
TG_MAGIC = _i("TG_MAGIC", 990011)                       # penanda order milik program ini
TG_DEVIATION_POINTS = _i("TG_DEVIATION_POINTS", 50)     # toleransi slippage (50 point = $0.05)
PAUSE_FILE = DATA_DIR / "PAUSE"                         # kill switch: file ada → tidak buka order

# ── Risk ────────────────────────────────────────────────────────────────────
TG_LOT = _f("TG_LOT", 0.01)
TG_MAX_POSITIONS = _i("TG_MAX_POSITIONS", 1)
TG_MAX_TRADES_DAY = _i("TG_MAX_TRADES_DAY", 40)
TG_DAILY_LOSS_USD = _f("TG_DAILY_LOSS_USD", 30.0)
TG_MAX_SPREAD_PIPS = _f("TG_MAX_SPREAD_PIPS", 5)
TG_DAY_TZ_HOURS = 7                                     # hari trading dihitung WIB


def pips_to_price(pips: float) -> float:
    """Satu-satunya konversi pip → jarak harga (RULES §4)."""
    return round(pips * PIP_SIZE, 2)
