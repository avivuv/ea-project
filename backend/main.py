import logging
import time
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from datetime import date as _date

from config import ALLOWED_PAIRS, HOST, PORT, AI_FILTER_ENABLED, AI_MIN_CONFIDENCE
from strategy_runner import run_all
from risk_manager import (
    check_risk, is_session_allowed,
    register_open_trade, register_close_trade, update_pnl,
    sync_open_trades, mark_profit_limit_hit,
)
from ai_filter import check_fundamental
from news_fetcher import get_news_context

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/ea.log", encoding="utf-8"),
        logging.StreamHandler(stream=__import__("sys").stdout),
    ],
)
# Force stdout ke UTF-8 agar karakter Unicode tidak crash di Windows
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
log = logging.getLogger(__name__)

app = FastAPI(title="EA Brain", version="2.0")

# ── Dedup open events (MT5 kadang kirim 2x untuk 1 trade) ────────────────────
_recent_open_ts: dict[str, float] = {}   # pair -> timestamp event terakhir
_OPEN_DEDUP_WINDOW = 10.0                # detik — event ke-2 dalam window ini diabaikan

# ── Zone blacklist (in-memory, reset harian) ──────────────────────────────────
# Mencegah re-entry ke zone yang sama setelah SL hit hari ini
_active_entry: dict[str, float] = {}   # pair -> entry_price trade aktif/pending
_zone_blacklist: dict[str, set] = {}   # pair -> set entry_price yang sudah SL hari ini
_zone_blacklist_day: str = ""

def _get_zone_blacklist() -> dict[str, set]:
    global _zone_blacklist, _zone_blacklist_day
    today = _date.today().isoformat()
    if _zone_blacklist_day != today:
        _zone_blacklist.clear()
        _zone_blacklist_day = today
    return _zone_blacklist

def _is_entry_blacklisted(pair: str, entry: float, tol: float = 0.003) -> bool:
    """Cek apakah entry price berada dalam radius zone yang sudah SL hari ini."""
    return any(
        e > 0 and abs(entry - e) / e <= tol
        for e in _get_zone_blacklist().get(pair, set())
    )


# ── Request / Response models ─────────────────────────────────────────────────

class Candle(BaseModel):
    time:   str
    open:   float
    high:   float
    low:    float
    close:  float
    volume: float = 0


class AnalyzeRequest(BaseModel):
    pair:             str
    equity:           float
    pip_value:        float = Field(..., description="Nilai 1 pip dalam currency akun")
    candles:          list[Candle] = Field(..., min_length=210)
    htf_candles:      list[Candle] = Field(default=[], description="Candle H1 untuk HTF confirmation")
    h4_candles:       list[Candle] = Field(default=[], description="Candle H4 untuk S&D zone detection")
    news_summary:     str = "No recent news available."
    upcoming_events:  str = "No high-impact events in 24h."
    open_trades:      list[str] = []


class TradeEvent(BaseModel):
    pair:      str
    event:     Literal["open", "close", "pending_placed", "pending_cancelled", "profit_limit_hit"]
    pnl_pct:   float = 0.0
    equity:    float


class AnalyzeResponse(BaseModel):
    action:        Literal["BUY", "SELL", "HOLD"]
    order_type:    Literal["MARKET", "LIMIT", "STOP"] = "MARKET"
    entry_price:   float = 0.0   # 0 = market order, >0 = pending order
    lot_size:      float = 0.0
    sl_price:      float = 0.0
    tp_price:      float = 0.0
    reason:        str
    strategy_id:   str   = ""
    ai_reasoning:  str   = ""
    ai_confidence: int   = 0
    ai_cached:     bool  = False


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    pair = req.pair.upper()

    if pair not in ALLOWED_PAIRS:
        log.warning(f"[{pair}] rejected — not in ALLOWED_PAIRS")
        raise HTTPException(400, f"Pair {pair} not in allowed list")

    log.info(f"[{pair}] analyze request | equity={req.equity} | pip_value={req.pip_value}")

    # GATE 1: Session filter
    if not is_session_allowed():
        log.info(f"[{pair}] HOLD — outside trading session")
        return AnalyzeResponse(action="HOLD", reason="outside_session")

    # GATE 2: Multi-strategy signal
    ohlcv     = [c.model_dump() for c in req.candles]
    htf_ohlcv = [c.model_dump() for c in req.htf_candles] if req.htf_candles else None
    h4_ohlcv  = [c.model_dump() for c in req.h4_candles]  if req.h4_candles  else None

    signal = run_all(ohlcv, pair=pair, htf_ohlcv=htf_ohlcv, h4_ohlcv=h4_ohlcv)

    log.info(
        f"[{pair}] signal={signal.direction} | strategy={signal.strategy_id} "
        f"| order={signal.order_type} | conf={signal.confidence:.2f} | reason={signal.reason}"
    )

    if signal.direction == "HOLD":
        return AnalyzeResponse(action="HOLD", reason=signal.reason, strategy_id=signal.strategy_id)

    # GATE 2.5: Zone blacklist — skip zone yang sudah SL hari ini
    if signal.entry_price > 0 and _is_entry_blacklisted(pair, signal.entry_price):
        log.info(f"[{pair}] HOLD — zone blacklisted | entry={signal.entry_price} already SL'd today")
        return AnalyzeResponse(action="HOLD", reason="zone_sl_blacklisted", strategy_id=signal.strategy_id)

    # GATE 3: AI fundamental filter (dapat dimatikan via AI_FILTER_ENABLED=false)
    if not AI_FILTER_ENABLED:
        log.info(f"[{pair}] AI filter disabled — skip Gate 3")
        ai_veto      = False
        ai_reasoning = "AI filter disabled"
        ai_confidence = 0
        ai_bias      = "DISABLED"
        ai_cached    = False
    else:
        tech_summary = {
            "strategy":   signal.strategy_id,
            "direction":  signal.direction,
            "order_type": signal.order_type,
            "reason":     signal.reason,
            "confidence": signal.confidence,
        }
        news_summary, upcoming_events = await get_news_context(pair)
        ai = await check_fundamental(
            pair=pair,
            direction=signal.direction,
            tech_summary=tech_summary,
            news_summary=news_summary,
            upcoming_events=upcoming_events,
        )
        ai_veto       = ai.veto
        ai_reasoning  = ai.reasoning
        ai_confidence = ai.confidence
        ai_bias       = ai.fundamental_bias
        ai_cached     = ai.cached
        veto_reason   = "ai_said_veto" if ai_veto and ai_confidence >= 60 else ("low_confidence" if ai_veto else "passed")
        log.info(
            f"[{pair}] AI veto={ai_veto} | conf={ai_confidence} | bias={ai_bias} "
            f"| cached={ai_cached} | reason={veto_reason} | reasoning={ai_reasoning[:120]}"
        )

    # Veto hanya dihormati jika AI confident (>= AI_MIN_CONFIDENCE)
    # AI conf=50 dan veto=True → AI tidak yakin → abaikan, lanjut
    if ai_veto and ai_confidence >= AI_MIN_CONFIDENCE:
        log.info(f"[{pair}] HOLD — strong AI veto | conf={ai_confidence} >= {AI_MIN_CONFIDENCE}")
        return AnalyzeResponse(
            action="HOLD",
            reason="ai_fundamental_veto",
            strategy_id=signal.strategy_id,
            ai_reasoning=ai_reasoning,
            ai_confidence=ai_confidence,
            ai_cached=ai_cached,
        )

    # GATE 4: Risk management
    if req.open_trades is not None:
        sync_open_trades(req.open_trades, req.equity)

    risk = check_risk(
        pair=pair,
        direction=signal.direction,
        equity=req.equity,
        sl_distance=signal.sl_distance,
        pip_value=req.pip_value,
    )
    log.info(f"[{pair}] risk check={risk.status} | lot={risk.lot_size} | reason={risk.reason}")

    if risk.status == "BLOCKED":
        return AnalyzeResponse(
            action="HOLD",
            reason=f"risk_blocked:{risk.reason}",
            strategy_id=signal.strategy_id,
            ai_reasoning=ai_reasoning,
            ai_confidence=ai_confidence,
            ai_cached=ai_cached,
        )

    # ── Hitung SL & TP price ──────────────────────────────────────────────────
    # Untuk LIMIT order, gunakan entry_price sebagai referensi
    # Untuk MARKET order, gunakan last close
    last_close = req.candles[-1].close
    entry_ref  = signal.entry_price if signal.order_type != "MARKET" and signal.entry_price > 0 else last_close

    if signal.direction == "BUY":
        sl_price = round(entry_ref - signal.sl_distance, 5)
        tp_price = round(entry_ref + signal.tp_distance, 5)
    else:
        sl_price = round(entry_ref + signal.sl_distance, 5)
        tp_price = round(entry_ref - signal.tp_distance, 5)

    log.info(
        f"[{pair}] EXECUTE {signal.direction} | strategy={signal.strategy_id} "
        f"| order={signal.order_type} | entry={entry_ref} | lot={risk.lot_size} "
        f"| sl={sl_price} | tp={tp_price}"
    )

    # Simpan entry untuk zone blacklist jika nanti kena SL
    if signal.entry_price > 0:
        _active_entry[pair] = signal.entry_price

    return AnalyzeResponse(
        action=signal.direction,
        order_type=signal.order_type,
        entry_price=round(signal.entry_price, 5),
        lot_size=risk.lot_size,
        sl_price=sl_price,
        tp_price=tp_price,
        reason=signal.reason,
        strategy_id=signal.strategy_id,
        ai_reasoning=ai_reasoning,
        ai_confidence=ai_confidence,
        ai_cached=ai_cached,
    )


@app.post("/trade-event")
async def trade_event(req: TradeEvent):
    """MT5 melapor saat trade dibuka, ditutup, atau pending order ditempatkan/dibatalkan."""
    pair = req.pair.upper()
    if req.event == "open":
        now = time.time()
        last_ts = _recent_open_ts.get(pair, 0.0)
        if now - last_ts < _OPEN_DEDUP_WINDOW:
            log.info(f"[{pair}] duplicate open event ignored ({now - last_ts:.1f}s since last)")
        else:
            _recent_open_ts[pair] = now
            register_open_trade(pair, req.equity)
            log.info(f"[{pair}] trade OPENED registered")
    elif req.event == "close":
        register_close_trade(pair, req.equity)
        update_pnl(req.pnl_pct, req.equity)
        log.info(f"[{pair}] trade CLOSED | pnl={req.pnl_pct:.2%}")
        if req.pnl_pct < 0 and pair in _active_entry:
            bl = _get_zone_blacklist()
            bl.setdefault(pair, set()).add(_active_entry[pair])
            log.info(f"[{pair}] zone blacklisted | entry={_active_entry[pair]} (SL hit)")
            del _active_entry[pair]
    elif req.event == "pending_placed":
        log.info(f"[{pair}] pending order PLACED")
    elif req.event == "pending_cancelled":
        _active_entry.pop(pair, None)
        log.info(f"[{pair}] pending order CANCELLED")
    elif req.event == "profit_limit_hit":
        mark_profit_limit_hit(req.equity)
        log.info(f"[{pair}] daily profit limit HIT — trading blocked for today")
    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
