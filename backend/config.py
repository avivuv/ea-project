import os
from dotenv import load_dotenv

load_dotenv()

# ── AI Provider ──────────────────────────────────────────────────────────────
AI_PROVIDER = "groq"                        # "gemini" | "groq"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

# ── Trading Parameters ────────────────────────────────────────────────────────
ALLOWED_PAIRS = [p.strip().upper() for p in os.getenv("ALLOWED_PAIRS", "EURUSD,GBPUSD,USDJPY,XAUUSD,BTCUSD,EURCHF").split(",")]

# RSI range khusus per pair
PAIR_RSI_CONFIG = {
    "XAUUSD": {"buy_min": 42, "buy_max": 72, "sell_min": 28, "sell_max": 58},
    "US500":  {"buy_min": 42, "buy_max": 72, "sell_min": 28, "sell_max": 58},
    "USTEC":  {"buy_min": 42, "buy_max": 72, "sell_min": 28, "sell_max": 58},
    "DEFAULT": {"buy_min": 45, "buy_max": 70, "sell_min": 30, "sell_max": 55},
}
TIMEFRAME = os.getenv("TIMEFRAME", "H4")

# Indikator
EMA_FAST = 50
EMA_SLOW = 200
RSI_PERIOD = 14
ATR_PERIOD = 14
ADX_PERIOD = 14
ADX_MIN_LEVEL = float(os.getenv("ADX_MIN_LEVEL", "20"))   # trend kuat jika ADX > 20
BODY_MULT     = float(os.getenv("BODY_MULT", "0.3"))      # candle body >= atr * BODY_MULT
HTF_CANDLE_COUNT = 100  # jumlah candle H1 yang dikirim untuk HTF confirmation

# EMA Slope filter (Gate 2) — pastikan EMA aktif trending, bukan flat
EMA_SLOPE_PERIOD  = int(os.getenv("EMA_SLOPE_PERIOD", "3"))        # lookback candle untuk hitung slope
EMA_SLOPE_MIN_PCT = float(os.getenv("EMA_SLOPE_MIN_PCT", "0.0001")) # min slope relatif terhadap harga (0.01%)

# Volume Spike filter (Gate 2) — bypass otomatis jika semua volume = 0
VOLUME_SPIKE_MULT = float(os.getenv("VOLUME_SPIKE_MULT", "1.5"))   # current vol harus > avg * mult
VOLUME_LOOKBACK   = int(os.getenv("VOLUME_LOOKBACK", "20"))         # jumlah candle untuk hitung avg volume

# Mode alternatif entry (off by default, aktifkan via .env)
ENABLE_RSI_DIVERGENCE = os.getenv("ENABLE_RSI_DIVERGENCE", "false").lower() == "true"
DIVERGENCE_LOOKBACK   = int(os.getenv("DIVERGENCE_LOOKBACK", "5"))  # candle lookback untuk deteksi divergence
ENABLE_PULLBACK_ENTRY = os.getenv("ENABLE_PULLBACK_ENTRY", "false").lower() == "true"
PULLBACK_ATR_MULT     = float(os.getenv("PULLBACK_ATR_MULT", "0.5")) # toleransi jarak ke EMA50 (N × ATR)

# RSI range untuk konfirmasi (hindari overbought/oversold ekstrem)
RSI_BUY_MIN = 45
RSI_BUY_MAX = 70
RSI_SELL_MIN = 30
RSI_SELL_MAX = 55

# ATR minimum threshold per pair (filter pasar flat/choppy)
# Nilai dalam satuan harga, sesuaikan jika perlu
ATR_MIN_THRESHOLD = {
    "XAUUSD": 3.0,      # Gold: minimal $3
    "EURUSD": 0.0003,   # 3 pips
    "GBPUSD": 0.0003,   # 3 pips
    "USDJPY": 0.03,     # 3 pips JPY
    "US500":  1.0,      # S&P500: minimal 1 point
    "USTEC":  5.0,      # Nasdaq 100: minimal 5 points
    "DEFAULT": 0.0003,
}

# SL & TP multiplier terhadap ATR (M5 butuh lebih besar supaya tidak kena noise)
SL_ATR_MULTIPLIER = float(os.getenv("SL_MULTIPLIER", "3.0"))
TP_ATR_MULTIPLIER = float(os.getenv("TP_MULTIPLIER", "5.0"))

# ── Risk Management ───────────────────────────────────────────────────────────
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PCT", "0.01"))   # default 1%
# Jika > 0: gunakan nominal tetap (misal $10) bukan % dari equity saat ini.
# Efek: lot tidak bertambah walau equity tumbuh — drawdown lebih terkontrol.
# Set 0 untuk fallback ke RISK_PER_TRADE_PCT × equity.
FIXED_RISK_USD = float(os.getenv("FIXED_RISK_USD", "10.0"))
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "6"))
MIN_LOT_SIZE = 0.01
MAX_LOT_SIZE = float(os.getenv("MAX_LOT_SIZE", "100.0"))  # absolute ceiling, jarang terpakai

# Ukuran 1 pip dalam satuan harga (Exness standard)
# Dipakai untuk konversi sl_distance (price units) → sl_in_pips
PIP_SIZE = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDJPY": 0.01,
    "XAUUSD": 0.01,    # Gold: 1 pip = $0.01
    "XAGUSD": 0.001,   # Silver: 1 pip = $0.001
    "USOIL":  1.0,     # WTI Oil Exness: pip = 1 price unit (EA sends 1000/pip/lot)
    "US500":  1.0,     # S&P500: 1 pip = 1 index point
    "USTEC":  1.0,     # Nasdaq 100: 1 pip = 1 index point
    "DEFAULT": 0.0001,
}

# Minimum pip_value yang masuk akal (Exness): nilai 1 pip per lot standar dalam USD
# Guard kalau MT5 kirim nilai aneh/nol
MIN_PIP_VALUE = {
    "XAUUSD": 1.0,
    "XAGUSD": 5.0,   # Silver Exness: $5.0/pip/lot — setelah fix MQL5 GetPipValue XAG case
    "USOIL":  500.0, # Oil Exness: pip=1.0 price unit, ~$1000/pip/lot — guard 50%
    "EURUSD": 1.0,
    "GBPUSD": 1.0,
    "USDJPY": 1.0,
    "US500":  1.0,
    "USTEC":  1.0,
    "DEFAULT": 1.0,
}

# Hard cap lot per-pair sebagai fallback jika kalkulasi meleset
# Bisa di-override via .env — tapi normalnya tidak perlu karena lot
# sudah dihitung otomatis dari equity × risk% / (sl_pips × pip_value)
MAX_LOT_BY_PAIR = {
    "EURUSD": float(os.getenv("MAX_LOT_EURUSD", "50.0")),
    "GBPUSD": float(os.getenv("MAX_LOT_GBPUSD", "50.0")),
    "USDJPY": float(os.getenv("MAX_LOT_USDJPY", "50.0")),
    "XAUUSD": float(os.getenv("MAX_LOT_XAUUSD", "50.0")),
    "XAGUSD": float(os.getenv("MAX_LOT_XAGUSD", "20.0")),
    "USOIL":  float(os.getenv("MAX_LOT_USOIL",  "10.0")),
    "US500":  float(os.getenv("MAX_LOT_US500",  "20.0")),
    "USTEC":  float(os.getenv("MAX_LOT_USTEC",  "20.0")),
    "DEFAULT": float(os.getenv("MAX_LOT_SIZE",  "50.0")),
}

DAILY_LOSS_LIMIT_PCT = 0.03     # stop trading hari ini jika rugi 3%
DAILY_PROFIT_LIMIT_USD = float(os.getenv("DAILY_PROFIT_LIMIT_USD", "0"))  # close all + stop jika profit harian >= nilai ini (0 = disabled)
MAX_DRAWDOWN_PCT = 0.12         # pause EA jika drawdown dari peak 12%

# Pair yang tidak boleh dibuka bersamaan (korelasi tinggi)
CORRELATION_FILTER = os.getenv("CORRELATION_FILTER", "true").lower() == "true"
CORRELATED_PAIRS = [
    {"EURUSD", "GBPUSD"},
    {"US500", "USTEC"},
    {"XAUUSD", "XAGUSD"},
]

# ── Session Filter (GMT) ──────────────────────────────────────────────────────
# SESSION_FILTER=true  → hanya London+NY (07:00-22:00 GMT)
# SESSION_FILTER=false → 24 jam, semua sesi
SESSION_FILTER = os.getenv("SESSION_FILTER", "false").lower() == "true"
ALLOWED_SESSIONS = [
    {"start": 0, "end": 19},    # Asia + London + NY overlap (00:00–19:00 UTC)
]
BLOCKED_MINUTES_BEFORE_NEWS = 30
BLOCKED_MINUTES_AFTER_NEWS = 30

# Minimum SL distance per pair (satuan harga) — hindari SL terlalu ketat
# EURUSD: 10 pip = 0.0010 | USDJPY: 10 pip = 0.10 | XAUUSD: $2 | US500: 5 pts
MIN_SL_DISTANCE = {
    "EURUSD": float(os.getenv("MIN_SL_EURUSD", "0.0010")),
    "GBPUSD": float(os.getenv("MIN_SL_GBPUSD", "0.0010")),
    "USDJPY": float(os.getenv("MIN_SL_USDJPY", "0.04")),
    "XAUUSD": float(os.getenv("MIN_SL_XAUUSD", "2.0")),
    "XAGUSD": float(os.getenv("MIN_SL_XAGUSD", "0.05")),  # 50 pip silver
    "USOIL":  float(os.getenv("MIN_SL_USOIL",  "0.10")),  # 0.10 price unit oil (~$100/lot)
    "US500":  float(os.getenv("MIN_SL_US500",  "30.0")),
    "USTEC":  float(os.getenv("MIN_SL_USTEC",  "150.0")),
    "EURCHF": float(os.getenv("MIN_SL_EURCHF", "0.0010")),
    "BTCUSD": float(os.getenv("MIN_SL_BTCUSD", "50.0")),
}

# ── AI Filter Thresholds ──────────────────────────────────────────────────────
AI_FILTER_ENABLED = os.getenv("AI_FILTER_ENABLED", "true").lower() == "true"
AI_MIN_CONFIDENCE = int(os.getenv("AI_MIN_CONFIDENCE", "60"))
AI_CACHE_SECONDS  = int(os.getenv("AI_CACHE_SECONDS", "7200"))

# ── Strategy 3: ADX Spike + Stochastic ───────────────────────────────────────
ADX_SPIKE_LOOKBACK      = int(os.getenv("ADX_SPIKE_LOOKBACK", "5"))
ADX_SPIKE_MIN_INCREASE  = float(os.getenv("ADX_SPIKE_MIN_INCREASE", "5.0"))
ADX_SPIKE_PCT_INCREASE  = float(os.getenv("ADX_SPIKE_PCT_INCREASE", "1.3"))
STOCH_K_PERIOD          = int(os.getenv("STOCH_K_PERIOD", "5"))
STOCH_D_PERIOD          = int(os.getenv("STOCH_D_PERIOD", "3"))
STOCH_OVERBOUGHT        = int(os.getenv("STOCH_OVERBOUGHT", "80"))
STOCH_OVERSOLD          = int(os.getenv("STOCH_OVERSOLD", "20"))
ADXSTOCH_SL_ATR_MULT    = float(os.getenv("ADXSTOCH_SL_ATR_MULT", "2.0"))
ADXSTOCH_RR             = float(os.getenv("ADXSTOCH_RR", "1.5"))

# ── Strategy 4: CHoCH + Order Block ──────────────────────────────────────────
CHOCH_SWING_PERIOD      = int(os.getenv("CHOCH_SWING_PERIOD", "15"))
CHOCH_OB_BODY_MIN       = float(os.getenv("CHOCH_OB_BODY_MIN", "0.6"))
CHOCH_OB_LOOKBACK       = int(os.getenv("CHOCH_OB_LOOKBACK", "30"))
CHOCH_MAX_OB_DIST_ATR   = float(os.getenv("CHOCH_MAX_OB_DIST_ATR", "4.0"))
CHOCH_OB_SL_BUFFER_ATR  = float(os.getenv("CHOCH_OB_SL_BUFFER_ATR", "0.3"))
CHOCH_RR                = float(os.getenv("CHOCH_RR", "2.0"))

# ── Strategy 5: Momentum / Impulse Candle ────────────────────────────────────
MOMENTUM_BODY_ATR_MULT  = float(os.getenv("MOMENTUM_BODY_ATR_MULT", "2.0"))
MOMENTUM_ADX_MIN        = float(os.getenv("MOMENTUM_ADX_MIN", "25.0"))
MOMENTUM_SL_ATR_MULT    = float(os.getenv("MOMENTUM_SL_ATR_MULT", "1.5"))
MOMENTUM_RR             = float(os.getenv("MOMENTUM_RR", "2.0"))

# ── Strategy 7: MACD Divergence ──────────────────────────────────────────────
MACD_FAST           = int(os.getenv("MACD_FAST", "12"))
MACD_SLOW           = int(os.getenv("MACD_SLOW", "26"))
MACD_SIGNAL         = int(os.getenv("MACD_SIGNAL", "9"))
MACD_DIV_LOOKBACK   = int(os.getenv("MACD_DIV_LOOKBACK", "20"))
MACD_SL_ATR_MULT    = float(os.getenv("MACD_SL_ATR_MULT", "2.0"))
MACD_RR             = float(os.getenv("MACD_RR", "2.0"))

# ── Strategy 8: Donchian Breakout ─────────────────────────────────────────────
DONCHIAN_PERIOD     = int(os.getenv("DONCHIAN_PERIOD", "20"))
DONCHIAN_ATR_MIN    = float(os.getenv("DONCHIAN_ATR_MIN", "0.5"))  # min ATR agar tidak entry di pasar flat
DONCHIAN_SL_ATR_MULT= float(os.getenv("DONCHIAN_SL_ATR_MULT", "2.0"))
DONCHIAN_RR         = float(os.getenv("DONCHIAN_RR", "2.0"))

# ── Strategy 5: Bollinger Bands Reversion ────────────────────────────────────
BB_PERIOD           = int(os.getenv("BB_PERIOD", "20"))
BB_STD              = float(os.getenv("BB_STD", "2.0"))
BB_RSI_OVERSOLD     = int(os.getenv("BB_RSI_OVERSOLD", "30"))
BB_RSI_OVERBOUGHT   = int(os.getenv("BB_RSI_OVERBOUGHT", "70"))
BB_SL_ATR_MULT      = float(os.getenv("BB_SL_ATR_MULT", "1.5"))
BB_RR               = float(os.getenv("BB_RR", "2.0"))

# ── Strategy 6: Fair Value Gap (FVG) ─────────────────────────────────────────
# HTF trend filter: hanya entry FVG searah H4 EMA trend (EMA20 vs EMA50)
FVG_HTF_TREND_FILTER = os.getenv("FVG_HTF_TREND_FILTER", "true").lower() == "true"
FVG_HTF_EMA_FAST     = int(os.getenv("FVG_HTF_EMA_FAST", "20"))
FVG_HTF_EMA_SLOW     = int(os.getenv("FVG_HTF_EMA_SLOW", "50"))
FVG_LOOKBACK        = int(os.getenv("FVG_LOOKBACK", "60"))
FVG_MIN_GAP_ATR     = float(os.getenv("FVG_MIN_GAP_ATR", "0.3"))   # gap minimum N × ATR
FVG_PROXIMITY_ATR   = float(os.getenv("FVG_PROXIMITY_ATR", "2.0")) # price harus dalam N × ATR dari FVG
FVG_SL_BUFFER_ATR   = float(os.getenv("FVG_SL_BUFFER_ATR", "0.6"))
FVG_SL_BUFFER_ATR_BY_PAIR: dict[str, float] = {
    "US500": 2.0, "USTEC": 2.0,
}
FVG_RR              = float(os.getenv("FVG_RR", "2.0"))
FVG_MAX_AGE_BARS    = int(os.getenv("FVG_MAX_AGE_BARS", "30"))      # zone lebih tua dari ini diabaikan
FVG_CONFIRM_BOUNCE  = os.getenv("FVG_CONFIRM_BOUNCE", "true").lower() == "true"  # tunggu candle reject zona
FVG_MAX_CHASE_ATR   = float(os.getenv("FVG_MAX_CHASE_ATR", "0.5"))  # max jarak entry dari zona setelah bounce (× ATR); lebih jauh → fallback LIMIT

# Per-pair FVG minimum gap override (pair lebih choppy butuh threshold lebih tinggi)
FVG_MIN_GAP_ATR_PAIRS: dict[str, float] = {}
for _item in os.getenv("FVG_MIN_GAP_ATR_PAIRS", "USDJPY:0.5,EURUSD:0.4,GBPUSD:0.4").split(","):
    if ":" in _item:
        _k, _v = _item.split(":", 1)
        FVG_MIN_GAP_ATR_PAIRS[_k.strip().upper()] = float(_v.strip())

# Pairs yang OBFVG-nya dimatikan (performa buruk di pair tertentu)
OBFVG_DISABLED_PAIRS = [p.strip().upper() for p in os.getenv("OBFVG_DISABLED_PAIRS", "USDJPY").split(",") if p.strip()]

# ── EMA_TREND Bounce Confirmation ────────────────────────────────────────────
EMA_CONFIRM_BOUNCE  = os.getenv("EMA_CONFIRM_BOUNCE", "true").lower() == "true"  # tunggu rejection di EMA50

# ── Strategy 10: Inverted Fair Value Gap (iFVG) ───────────────────────────────
IFVG_LOOKBACK       = int(os.getenv("IFVG_LOOKBACK", "80"))
IFVG_MIN_GAP_ATR    = float(os.getenv("IFVG_MIN_GAP_ATR", "0.3"))
IFVG_PROXIMITY_ATR  = float(os.getenv("IFVG_PROXIMITY_ATR", "2.0"))
IFVG_SL_BUFFER_ATR  = float(os.getenv("IFVG_SL_BUFFER_ATR", "0.6"))
IFVG_SL_BUFFER_ATR_BY_PAIR: dict[str, float] = {
    "US500": 2.0, "USTEC": 2.0,
}
IFVG_RR             = float(os.getenv("IFVG_RR", "2.0"))
IFVG_MAX_AGE_BARS   = int(os.getenv("IFVG_MAX_AGE_BARS", "30"))     # zone lebih tua dari ini diabaikan

# ── Strategy 2: Supply & Demand ───────────────────────────────────────────────
SD_IMPULSE_ATR_MULT      = float(os.getenv("SD_IMPULSE_ATR_MULT", "1.5"))   # body impulse >= N × ATR
SD_BASE_ATR_MULT         = float(os.getenv("SD_BASE_ATR_MULT", "0.5"))      # body base <= N × ATR
SD_BASE_CANDLES          = int(os.getenv("SD_BASE_CANDLES", "3"))           # max candle dalam base
SD_LOOKBACK              = int(os.getenv("SD_LOOKBACK", "100"))             # candle H4 yang discan
SD_PROXIMITY_ATR         = float(os.getenv("SD_PROXIMITY_ATR", "4.0"))      # radius mendekati zone (N × ATR H4)
SD_ZONE_BUFFER_ATR       = float(os.getenv("SD_ZONE_BUFFER_ATR", "0.3"))    # buffer SL di luar zone
SD_TP_ATR_MULT           = float(os.getenv("SD_TP_ATR_MULT", "4.0"))        # TP = N × ATR H4
SD_H4_EMA_CONFIRM        = os.getenv("SD_H4_EMA_CONFIRM", "true").lower() == "true"
SD_H4_EMA_FAST           = int(os.getenv("SD_H4_EMA_FAST", "20"))           # EMA cepat khusus H4 (fit dalam 120 bar)
SD_H4_EMA_SLOW           = int(os.getenv("SD_H4_EMA_SLOW", "50"))           # EMA lambat khusus H4 (fit dalam 120 bar)
SD_MIN_STRENGTH          = float(os.getenv("SD_MIN_STRENGTH", "0.3"))       # min kekuatan zone
SD_PENDING_EXPIRY_CANDLES = int(os.getenv("SD_PENDING_EXPIRY_CANDLES", "4")) # batal jika N candle tidak fill

# ── Strategy 11: Opening Range Breakout (ORB) ────────────────────────────────
ORB_RANGE_CANDLES        = int(os.getenv("ORB_RANGE_CANDLES", "2"))           # jumlah M15 candle untuk opening range (2 = 30 menit)
ORB_MAX_BREAKOUT_CANDLES = int(os.getenv("ORB_MAX_BREAKOUT_CANDLES", "8"))    # maks candle setelah range untuk entry (2 jam)
ORB_MIN_RANGE_ATR        = float(os.getenv("ORB_MIN_RANGE_ATR", "0.3"))       # min range size (N × ATR)
ORB_SL_BUFFER_ATR        = float(os.getenv("ORB_SL_BUFFER_ATR", "0.3"))       # buffer SL di luar range
ORB_RR                   = float(os.getenv("ORB_RR", "2.0"))                  # TP = range_size × RR
ORB_SESSION_UTC: dict[str, tuple[int, int]] = {                                # (hour, minute) UTC sesi per pair
    "EURUSD": (8, 0),
    "GBPUSD": (8, 0),
    "USDJPY": (8, 0),
    "XAUUSD": (8, 0),
    "XAGUSD": (8, 0),
    "USOIL":  (13, 30),  # Oil aktif saat NY open
    "EURCHF": (8, 0),
    "US500":  (13, 30),
    "USTEC":  (13, 30),
    "BTCUSD": (8, 0),
}

# ── Strategy OB+FVG — Order Block + Fair Value Gap (SND Skenario 2) ──────────
OBFVG_ENABLED         = os.getenv("OBFVG_ENABLED", "false").lower() == "true"
OBFVG_LOOKBACK        = int(os.getenv("OBFVG_LOOKBACK", "50"))        # candle H4 yang discan
OBFVG_IMPULSE_ATR     = float(os.getenv("OBFVG_IMPULSE_ATR", "1.5")) # min impulse setelah OB (N × ATR H4)
OBFVG_PROXIMITY_ATR   = float(os.getenv("OBFVG_PROXIMITY_ATR", "3.0")) # radius price ke OB (N × ATR H4)
OBFVG_SL_BUFFER_ATR   = float(os.getenv("OBFVG_SL_BUFFER_ATR", "0.3"))
OBFVG_SL_BUFFER_ATR_BY_PAIR: dict[str, float] = {
    "US500": 1.5, "USTEC": 1.5,
}
OBFVG_RR              = float(os.getenv("OBFVG_RR", "3.0"))           # RR 1:3 sesuai dokumen
OBFVG_FVG_REQUIRED    = os.getenv("OBFVG_FVG_REQUIRED", "true").lower() == "true"
OBFVG_HTF_EMA_FAST    = int(os.getenv("OBFVG_HTF_EMA_FAST", "50"))
OBFVG_HTF_EMA_SLOW    = int(os.getenv("OBFVG_HTF_EMA_SLOW", "200"))  # EMA 50/200 sesuai dokumen SND
OBFVG_MAX_OB_AGE      = int(os.getenv("OBFVG_MAX_OB_AGE", "30"))     # OB lebih tua dari ini diabaikan

# ── Strategy OB_CONFIRM — Order Block + Candle Confirmation ──────────────────
OB_CONFIRM_ENABLED        = os.getenv("OB_CONFIRM_ENABLED", "true").lower() == "true"
OB_CONFIRM_ENGULF         = os.getenv("OB_CONFIRM_ENGULF", "true").lower() == "true"   # aktifkan tipe engulfing
OB_CONFIRM_REJECTION      = os.getenv("OB_CONFIRM_REJECTION", "true").lower() == "true" # aktifkan tipe rejection/pin bar
OB_CONFIRM_LOOKBACK       = int(os.getenv("OB_CONFIRM_LOOKBACK", "50"))
OB_CONFIRM_IMPULSE_ATR    = float(os.getenv("OB_CONFIRM_IMPULSE_ATR", "1.5"))  # min impulse H4 untuk OB valid
OB_CONFIRM_PROXIMITY_ATR  = float(os.getenv("OB_CONFIRM_PROXIMITY_ATR", "1.0")) # radius price ke zona OB (N × H4 ATR)
OB_CONFIRM_SL_BUFFER_ATR  = float(os.getenv("OB_CONFIRM_SL_BUFFER_ATR", "0.5"))
OB_CONFIRM_SL_BUFFER_ATR_BY_PAIR: dict[str, float] = {
    "US500": 2.0, "USTEC": 2.0,
}
OB_CONFIRM_RR             = float(os.getenv("OB_CONFIRM_RR", "3.0"))
OB_CONFIRM_MAX_OB_AGE     = int(os.getenv("OB_CONFIRM_MAX_OB_AGE", "20"))    # base max age (tanpa flag kualitas)
OB_CONFIRM_AGE_BONUS_FVG  = int(os.getenv("OB_CONFIRM_AGE_BONUS_FVG",  "10")) # +N bar jika ada FVG
OB_CONFIRM_AGE_BONUS_BOS  = int(os.getenv("OB_CONFIRM_AGE_BONUS_BOS",  "10")) # +N bar jika ada BOS
OB_CONFIRM_AGE_BONUS_SWEEP= int(os.getenv("OB_CONFIRM_AGE_BONUS_SWEEP","15")) # +N bar jika ada liquidity sweep
OB_CONFIRM_ENGULF_RATIO   = float(os.getenv("OB_CONFIRM_ENGULF_RATIO", "1.3"))  # body > 1.3× body prev
OB_CONFIRM_REJECTION_WICK = float(os.getenv("OB_CONFIRM_REJECTION_WICK", "2.0")) # wick > 2× body
OB_CONFIRM_HTF_EMA_FAST   = int(os.getenv("OB_CONFIRM_HTF_EMA_FAST", "50"))
OB_CONFIRM_HTF_EMA_SLOW   = int(os.getenv("OB_CONFIRM_HTF_EMA_SLOW", "200"))
OB_CONFIRM_DISABLED_PAIRS = [p.strip().upper() for p in os.getenv("OB_CONFIRM_DISABLED_PAIRS", "").split(",") if p.strip()]
# SMC quality filters
OB_CONFIRM_REQUIRE_FVG    = os.getenv("OB_CONFIRM_REQUIRE_FVG", "false").lower() == "true"  # bonus saja, bukan wajib
OB_CONFIRM_REQUIRE_BOS    = os.getenv("OB_CONFIRM_REQUIRE_BOS", "false").lower() == "true"  # bonus saja, bukan wajib
OB_CONFIRM_REQUIRE_PD     = os.getenv("OB_CONFIRM_REQUIRE_PD", "true").lower() == "true"    # OB harus di premium/discount zone
OB_CONFIRM_PD_LOOKBACK    = int(os.getenv("OB_CONFIRM_PD_LOOKBACK", "50"))                  # bar H4 untuk hitung swing H/L
OB_CONFIRM_MIN_ZONE_ATR   = float(os.getenv("OB_CONFIRM_MIN_ZONE_ATR", "0.3"))              # lebar zona minimal N × ATR
# LTF (M15) CHoCH + OB entry
OB_CONFIRM_CHOCH_PERIOD   = int(os.getenv("OB_CONFIRM_CHOCH_PERIOD", "5"))     # swing period M15 untuk CHoCH
OB_CONFIRM_LTF_LOOKBACK   = int(os.getenv("OB_CONFIRM_LTF_LOOKBACK", "30"))    # M15 bars untuk scan LTF OB setelah CHoCH
OB_CONFIRM_LTF_FVG_REQ    = os.getenv("OB_CONFIRM_LTF_FVG_REQ", "true").lower() == "true"  # wajib FVG di M15 OB
OB_CONFIRM_LTF_SL_BUFFER  = float(os.getenv("OB_CONFIRM_LTF_SL_BUFFER", "0.5"))            # buffer SL = N × M15 ATR
# Liquidity Sweep detection
OB_CONFIRM_REQUIRE_SWEEP  = os.getenv("OB_CONFIRM_REQUIRE_SWEEP", "false").lower() == "true" # wajib ada sweep (default off - bonus saja)
OB_CONFIRM_SWEEP_LOOKBACK = int(os.getenv("OB_CONFIRM_SWEEP_LOOKBACK", "30"))   # bar H4 untuk cari level likuiditas
OB_CONFIRM_SWEEP_WINDOW   = int(os.getenv("OB_CONFIRM_SWEEP_WINDOW", "5"))      # bar sebelum OB untuk cek sweep candle
OB_CONFIRM_SWEEP_TOL_ATR  = float(os.getenv("OB_CONFIRM_SWEEP_TOL_ATR", "0.3")) # toleransi equal H/L = N × ATR

# ── Order Block zone definition ───────────────────────────────────────────────
# Jika body / candle_range >= threshold → zona = High ke Low (full candle, SMC standar)
# Jika body / candle_range < threshold  → zona = Open ke Close (body only, wick terlalu panjang)
# 0.35 = batas wajar: candle dengan body < 35% dari total range (pin bar, doji) → pakai body
OB_WICK_THRESHOLD = float(os.getenv("OB_WICK_THRESHOLD", "0.35"))

# ── Strategy BUMI — 4 MA Cross (SMA 5, 13, 21, 34) ──────────────────────────
BUMI_ENABLED      = os.getenv("BUMI_ENABLED", "false").lower() == "true"
BUMI_MA_FAST      = int(os.getenv("BUMI_MA_FAST", "5"))
BUMI_MA_2         = int(os.getenv("BUMI_MA_2", "13"))
BUMI_MA_3         = int(os.getenv("BUMI_MA_3", "21"))
BUMI_MA_SLOW      = int(os.getenv("BUMI_MA_SLOW", "34"))
BUMI_WAIT_ORDERED = os.getenv("BUMI_WAIT_ORDERED", "true").lower() == "true"  # tunggu 4 MA berurutan
BUMI_ENGULF_CONF  = os.getenv("BUMI_ENGULF_CONF", "false").lower() == "true"  # wajib engulfing konfirmasi
BUMI_SL_ATR_MULT  = float(os.getenv("BUMI_SL_ATR_MULT", "1.5"))
BUMI_RR           = float(os.getenv("BUMI_RR", "4.0"))                         # RR 1:4 sesuai dokumen
BUMI_LOOKBACK     = int(os.getenv("BUMI_LOOKBACK", "3"))                        # candle lookback cek cross

# ── Strategy BPR — Balanced Price Range (M15) ────────────────────────────────
BPR_ENABLED            = os.getenv("BPR_ENABLED", "true").lower() == "true"
BPR_LOOKBACK           = int(os.getenv("BPR_LOOKBACK", "100"))        # M15 bars discan (≈25 jam)
BPR_MIN_GAP_ATR        = float(os.getenv("BPR_MIN_GAP_ATR", "0.3"))   # ukuran FVG minimum (N × ATR)
BPR_PROXIMITY_ATR      = float(os.getenv("BPR_PROXIMITY_ATR", "1.5")) # jarak max price ke zona (N × ATR)
BPR_DISPLACEMENT_RATIO = float(os.getenv("BPR_DISPLACEMENT_RATIO", "0.5"))  # body C2 min 50% dari range
BPR_SL_BUFFER_ATR      = float(os.getenv("BPR_SL_BUFFER_ATR", "0.3"))
BPR_SL_BUFFER_ATR_BY_PAIR: dict[str, float] = {
    "US500": 1.5, "USTEC": 1.5,
}
BPR_RR                 = float(os.getenv("BPR_RR", "3.0"))            # target RR 1:3
BPR_MAX_AGE_BARS       = int(os.getenv("BPR_MAX_AGE_BARS", "60"))     # BPR lebih tua dari ini diabaikan (≈15 jam M15)
BPR_MAX_TEMPORAL_GAP   = int(os.getenv("BPR_MAX_TEMPORAL_GAP", "24"))  # jarak max bars antar dua FVG (ICT V-shape ~6 jam M15)
BPR_MAX_CHASE_ATR      = float(os.getenv("BPR_MAX_CHASE_ATR", "0.5")) # max jarak entry dari zona setelah bounce
BPR_HTF_TREND_FILTER   = os.getenv("BPR_HTF_TREND_FILTER", "true").lower() == "true"
BPR_HTF_EMA_FAST       = int(os.getenv("BPR_HTF_EMA_FAST", "20"))    # H4 EMA cepat
BPR_HTF_EMA_SLOW       = int(os.getenv("BPR_HTF_EMA_SLOW", "50"))    # H4 EMA lambat
BPR_DISABLED_PAIRS     = [p.strip().upper() for p in os.getenv("BPR_DISABLED_PAIRS", "").split(",") if p.strip()]

# Per-pair BPR minimum gap override (pair choppy butuh threshold lebih tinggi)
BPR_MIN_GAP_ATR_PAIRS: dict[str, float] = {}
for _item in os.getenv("BPR_MIN_GAP_ATR_PAIRS", "USDJPY:0.5,EURUSD:0.4,GBPUSD:0.4").split(","):
    if ":" in _item:
        _k, _v = _item.split(":", 1)
        BPR_MIN_GAP_ATR_PAIRS[_k.strip().upper()] = float(_v.strip())

# ── Strategy Runner ───────────────────────────────────────────────────────────
MIN_SIGNAL_CONF     = float(os.getenv("MIN_SIGNAL_CONF", "0.55"))   # sinyal di bawah ini diabaikan sebelum aggregasi
MIN_STRATEGIES_CONFIRM = int(os.getenv("MIN_STRATEGIES_CONFIRM", "2"))  # min strategi searah untuk execute
SINGLE_HIGH_CONF    = float(os.getenv("SINGLE_HIGH_CONF", "0.75"))  # satu strategi boleh execute jika conf >= ini

# ── Server ────────────────────────────────────────────────────────────────────
HOST = "0.0.0.0"
PORT = 8000
