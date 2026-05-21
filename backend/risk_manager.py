import json
import os
from datetime import datetime, timezone, date
from dataclasses import dataclass, asdict
from typing import Literal
from config import (
    RISK_PER_TRADE_PCT, FIXED_RISK_USD, MAX_OPEN_TRADES,
    DAILY_PROFIT_LIMIT_USD,
    CORRELATED_PAIRS, CORRELATION_FILTER, ALLOWED_SESSIONS,
    MIN_LOT_SIZE, MAX_LOT_SIZE, MAX_LOT_BY_PAIR, SESSION_FILTER,
    MIN_PIP_VALUE, PIP_SIZE, MIN_SL_DISTANCE,
)

STATE_FILE = os.path.join(os.path.dirname(__file__), "state", "risk_state.json")

RiskStatus = Literal["OK", "BLOCKED"]


@dataclass
class RiskState:
    date: str                        # YYYY-MM-DD, reset setiap hari baru
    daily_pnl: float                 # kumulatif P&L hari ini (dalam %)
    equity_peak: float               # equity tertinggi sejak EA jalan
    open_trades: list[str]           # list pair yang sedang open
    ea_paused: bool                  # True jika max drawdown tercapai
    daily_profit_limit_hit: bool = False  # True jika profit harian >= DAILY_PROFIT_LIMIT_USD


@dataclass
class RiskCheckResult:
    status: RiskStatus
    reason: str
    lot_size: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0


# ── State persistence ─────────────────────────────────────────────────────────

def _load_state(equity: float) -> RiskState:
    today = date.today().isoformat()
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            data = json.load(f)
        data.setdefault("daily_profit_limit_hit", False)
        state = RiskState(**data)
        if state.date != today:
            # Reset daily stats, pertahankan equity_peak dan ea_paused
            state.date = today
            state.daily_pnl = 0.0
            state.open_trades = []
            state.daily_profit_limit_hit = False
            _save_state(state)
        return state

    state = RiskState(
        date=today,
        daily_pnl=0.0,
        equity_peak=equity,
        open_trades=[],
        ea_paused=False,
    )
    _save_state(state)
    return state


def _save_state(state: RiskState):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(asdict(state), f, indent=2)


# ── Public API ────────────────────────────────────────────────────────────────

def update_pnl(pnl_pct: float, equity: float):
    """Dipanggil MT5 saat trade close untuk update state harian."""
    state = _load_state(equity)
    state.daily_pnl += pnl_pct
    if equity > state.equity_peak:
        state.equity_peak = equity
    _save_state(state)


def register_open_trade(pair: str, equity: float):
    state = _load_state(equity)
    if pair not in state.open_trades:
        state.open_trades.append(pair)
    _save_state(state)


def sync_open_trades(open_pairs: list[str], equity: float):
    """Override open_trades di state dengan data aktual dari MT5."""
    state = _load_state(equity)
    state.open_trades = [p.upper() for p in open_pairs]
    _save_state(state)


def register_close_trade(pair: str, equity: float):
    state = _load_state(equity)
    if pair in state.open_trades:
        state.open_trades.remove(pair)
    _save_state(state)


def mark_profit_limit_hit(equity: float):
    """Dipanggil saat MT5 melaporkan profit harian limit tercapai."""
    state = _load_state(equity)
    state.daily_profit_limit_hit = True
    _save_state(state)


def check_risk(
    pair: str,
    direction: str,
    equity: float,
    sl_distance: float,
    pip_value: float,
) -> RiskCheckResult:
    """
    Gate 4: validasi semua risk rules sebelum eksekusi.
    Return RiskCheckResult dengan lot_size, sl_price, tp_price jika OK.
    """
    state = _load_state(equity)

    # Cek max open trades
    if len(state.open_trades) >= MAX_OPEN_TRADES:
        return RiskCheckResult("BLOCKED", f"max_open_trades_{MAX_OPEN_TRADES}")

    # Cek pair sudah ada posisi terbuka
    if pair in state.open_trades:
        return RiskCheckResult("BLOCKED", f"already_have_position_{pair}")

    # Cek korelasi — jangan buka jika pair berkorelasi sudah open
    if CORRELATION_FILTER:
        for group in CORRELATED_PAIRS:
            if pair in group:
                conflict = group - {pair}
                for open_pair in state.open_trades:
                    if open_pair in conflict:
                        return RiskCheckResult("BLOCKED", f"correlated_pair_open:{open_pair}")

    # Cek minimum SL distance — hindari SL terlalu ketat yang bikin lot meledak
    min_sl = MIN_SL_DISTANCE.get(pair.upper(), 0.0)
    if sl_distance < min_sl:
        return RiskCheckResult("BLOCKED", f"sl_too_tight:{sl_distance:.5f}<min{min_sl}")

    # Hitung position size
    if sl_distance <= 0 or pip_value <= 0:
        return RiskCheckResult("BLOCKED", "invalid_sl_or_pip_value")

    # Guard: pip_value terlalu kecil → lot akan meledak
    min_pv = MIN_PIP_VALUE.get(pair.upper(), MIN_PIP_VALUE["DEFAULT"])
    effective_pip_value = max(pip_value, min_pv)

    # Konversi sl_distance (satuan harga) → sl_in_pips
    # Contoh XAUUSD: sl_distance=15.0 price / 0.01 pip_size = 1500 pip
    pip_size = PIP_SIZE.get(pair.upper(), PIP_SIZE["DEFAULT"])
    sl_in_pips = sl_distance / pip_size

    # lot = risk_amount / (sl_in_pips × pip_value_per_lot)
    # pip_value dari MT5 = nilai 1 pip per lot standar (misal XAUUSD ~$1, EURUSD ~$10)
    risk_amount = FIXED_RISK_USD if FIXED_RISK_USD > 0 else equity * RISK_PER_TRADE_PCT
    raw_lot = risk_amount / (sl_in_pips * effective_pip_value)

    # Hard cap absolut sebagai safety net jika ada data aneh dari MT5
    pair_max_lot = MAX_LOT_BY_PAIR.get(pair.upper(), MAX_LOT_BY_PAIR["DEFAULT"])
    effective_max_lot = min(MAX_LOT_SIZE, pair_max_lot)

    lot_size = round(max(MIN_LOT_SIZE, min(raw_lot, effective_max_lot)), 2)

    return RiskCheckResult(
        status="OK",
        reason="all_checks_passed",
        lot_size=lot_size,
    )


def is_session_allowed() -> bool:
    if not SESSION_FILTER:
        return True
    now_hour = datetime.now(timezone.utc).hour
    for session in ALLOWED_SESSIONS:
        if session["start"] <= now_hour < session["end"]:
            return True
    return False
