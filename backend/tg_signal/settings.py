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
# Terminal MT5 yang dipakai SEMUA modul. Wajib eksplisit: bila >1 terminal jalan, initialize() tanpa path
# menempel ke terminal sembarang (pernah: dashboard membaca akun REAL di terminal "COPY").
MT5_TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH", r"C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe")


def mt5_init_kwargs() -> dict:
    return {"path": MT5_TERMINAL_PATH} if MT5_TERMINAL_PATH else {}
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
TG_DUPLICATE_WINDOW_SEC = _i("TG_DUPLICATE_WINDOW_SEC", 0)   # 0 = tanpa filter duplikat (16 Nov 2026: user minta semua sinyal diproses)
TG_EDIT_MAX_SEC = _i("TG_EDIT_MAX_SEC", 600)  # edit sinyal (typo dibenerin admin) diproses ulang bila ≤ ini dari waktu kirim
TG_POLL_SEC = _f("TG_POLL_SEC", 3)         # cek aktif pesan baru (push Telegram bisa telat ±60 dtk)

# ── Eksekusi (Tahap 4, akun demo) ───────────────────────────────────────────
# ZONE (keputusan user 12 Nov 2026): sudah di zona → market, belum → pending limit di ZERO,
#      SL = LAST ∓ TG_SL_PIPS. MARKET: entry market saat sinyal diterima, SL dari TG_SL_FROM.
#      12 Nov 2026 (malam): user minta kembali ke MARKET sebagai default.
# POI (keputusan user 13 Nov 2026): detektor FVG/OB/IFVG mencari POI di dalam zona sinyal → pending di
#      POI terdekat (tanpa POI → pending di ZERO); harga sudah di zona → market. SL/TP dari harga entry.
#      Pending dipindah tiap bar baru bila POI gagal / muncul POI yang lebih dekat. Lihat entry_plan.plan_poi.
TG_ENTRY_MODE = os.getenv("TG_ENTRY_MODE", "POI").upper()     # MARKET | ZONE | POI
TG_POI_TF = os.getenv("TG_POI_TF", "M1").upper()               # timeframe deteksi POI
TG_POI_BARS = _i("TG_POI_BARS", 300)                           # jumlah bar yang dipindai
TG_POI_MAX_AGE = _i("TG_POI_MAX_AGE", 240)                     # umur maks POI (bar)
TG_POI_TOL = _f("TG_POI_TOL", 0.5)                             # zona diperlebar $ ini saat cari POI
TG_POI_MIN_SIZE = _f("TG_POI_MIN_SIZE", 0.2)                   # ukuran minimum FVG/OB ($)
# Tanpa POI di zona: NONE = sinyal WAITING, dicek ulang tiap bar sampai POI terbentuk / sinyal selesai
# (keputusan user 13 Nov 2026: sedikit order tapi presisi) | ZERO = pending di ZERO seperti mode ZONE
TG_POI_FALLBACK = os.getenv("TG_POI_FALLBACK", "NONE").upper()
# 1 = sinyal baru membatalkan pending/WAITING lama; 0 = semua sinyal tetap jalan berdampingan (16 Nov 2026)
TG_POI_REPLACE_PENDING = _i("TG_POI_REPLACE_PENDING", 0)
# Admin sudah "tp" (lihat TG_ADMIN_TP_SOURCE) tapi posisi kita belum TP → TP diturunkan ke
# entry ± ini (harga sudah lewat → tutup). Keputusan user 13 Nov 2026; backtest admin_tp_study.py:
# rugi berkurang ~30–50% di dua periode. 0 = off.
TG_ADMIN_TP_PIPS = _f("TG_ADMIN_TP_PIPS", 20)
# Pemicu admin TP: REPORT (default, keputusan user 16 Nov 2026 — "sudah TP" murni dari chat admin Telegram:
# baris baru "✅ ...-TP" di Report atau pesan singkat TP/MID/INSTAN); PRICE = harga sampai ZERO ± TG_EXPIRE_TP_PIPS;
# BOTH = mana yang duluan.
TG_ADMIN_TP_SOURCE = os.getenv("TG_ADMIN_TP_SOURCE", "REPORT").upper()
TG_REPORT_LOOKBACK_H = _f("TG_REPORT_LOOKBACK_H", 12)   # baris Report hanya dicocokkan ke sinyal ≤ sekian jam
TG_TP_PIPS = _f("TG_TP_PIPS", 30)                       # TP = SL = 30 pips (keputusan user)
TG_SL_FROM = os.getenv("TG_SL_FROM", "entry")           # entry | zone (LAST − SL)
TG_MAGIC = _i("TG_MAGIC", 990011)                       # penanda order milik program ini
TG_DEVIATION_POINTS = _i("TG_DEVIATION_POINTS", 50)     # toleransi slippage (50 point = $0.05)
PAUSE_FILE = DATA_DIR / "PAUSE"                         # kill switch GLOBAL: file ada → semua metode tidak buka order
# Pause per metode (18 Nov 2026): file ada → metode itu tidak buka order baru; posisi terbuka tetap dikelola.
PAUSE_TG = DATA_DIR / "PAUSE_TG"                        # EA sinyal Telegram (run_live)
PAUSE_PRO = DATA_DIR / "PAUSE_PRO"                      # SMC Top-Down (pro_live)
PAUSE_ORB = DATA_DIR / "PAUSE_ORB"                      # ORB NY, semua instrumen (orb_live)
PAUSE_SWING = DATA_DIR / "PAUSE_SWING"                  # swing Donchian (intraday.swing_live)
PAUSE_MAC = DATA_DIR / "PAUSE_MAC"                    # Trend MA Cross (mac_live)


def is_paused(method_file: Path) -> bool:
    """True bila pause global atau pause metode itu aktif."""
    return PAUSE_FILE.exists() or method_file.exists()

# ── Risk ────────────────────────────────────────────────────────────────────
TG_LOT = _f("TG_LOT", 0.01)
TG_MAX_POSITIONS = _i("TG_MAX_POSITIONS", 0)            # 0 = tanpa batas (13 Nov 2026: user minta semua sinyal dieksekusi)
TG_MAX_TRADES_DAY = _i("TG_MAX_TRADES_DAY", 40)
TG_DAILY_LOSS_USD = _f("TG_DAILY_LOSS_USD", 30.0)
TG_DAILY_PROFIT_USD = _f("TG_DAILY_PROFIT_USD", 100.0) # tertutup+floating >= ini → tutup semua & stop; 0 = off (dibuat tinggi: BT $10 tidak membantu)
TG_MAX_SPREAD_PIPS = _f("TG_MAX_SPREAD_PIPS", 5)
TG_DAY_TZ_HOURS = 7                                     # hari trading dihitung WIB


def pips_to_price(pips: float) -> float:
    """Satu-satunya konversi pip → jarak harga (RULES §4)."""
    return round(pips * PIP_SIZE, 2)

# ── Strategi sendiri (pro_live.py, keputusan user 13 Nov 2026: langsung DEMO) ──────────────
PRO_MAGIC = _i("PRO_MAGIC", 990022)                     # beda dari TG_MAGIC: order tidak tercampur
PRO_LOT = _f("PRO_LOT", 0.01)
PRO_BARS = _i("PRO_BARS", 3000)                         # bar M5 yang dibaca tiap bar baru (~10 hari)
PRO_NEWS_MIN = _f("PRO_NEWS_MIN", 15)                   # +- menit dari news HIGH USD: tanpa setup/entry baru; 0 = off
