import json
import time
import asyncio
import httpx
from datetime import datetime, timezone
from dataclasses import dataclass
from config import (
    AI_PROVIDER, GEMINI_API_KEY, GEMINI_MODEL,
    GROQ_API_KEY, GROQ_MODEL,
    AI_MIN_CONFIDENCE, AI_CACHE_SECONDS,
)

_cache: dict[str, dict] = {}
_rate_limit_until: float = 0


@dataclass
class AIFilterResult:
    veto: bool
    confidence: int
    fundamental_bias: str
    reasoning: str
    cached: bool = False


SYSTEM_PROMPT = """You are a forex trade risk filter. Your ONLY job: identify specific fundamental reasons to BLOCK a trade.

CRITICAL MINDSET: You are a veto system, not a signal generator.
- Default answer = APPROVE (veto: false, confidence: 65)
- Only veto when you can cite a SPECIFIC, CONCRETE fundamental reason
- "I don't have enough news" = APPROVE, not VETO
- Uncertainty always favors the trade

VETO ONLY for these specific situations:
1. High-impact economic event within 2 hours for either currency (check upcoming_events carefully)
2. Breaking news with a clear macro narrative directly opposing the trade direction
3. Systemic risk event: emergency central bank action, circuit breaker, geopolitical shock

NEVER veto because:
- News context is sparse or unavailable → set veto: false, confidence: 65
- You are generally "uncertain" without specific catalyst
- General market volatility without directional implication

CONFIDENCE CALIBRATION:
- 80-95: You have specific headline/event that clearly supports or opposes the trade
- 65-79: Moderate relevant news exists
- 55-64: Minimal news, or news only loosely related to this pair
- When veto: false due to no news → use 65

PAIR BIAS GUIDE (use as context, not absolute rule):
- USD pairs: Fed stance, US employment, CPI, Treasury yields
- EUR pairs: ECB policy, Eurozone PMI, German data
- GBP pairs: Bank of England, UK CPI, Brexit spillover
- JPY pairs: BoJ intervention risk, risk-off flows, yield differential
- XAU: risk-off demand, real yields, Fed pivot expectations
- US500/USTEC: risk sentiment, Fed, earnings season, recession fear

Respond with valid JSON only. No markdown.
{
  "reasoning": "Cite SPECIFIC headline or event. If no news: write 'No fundamental catalyst — approving technical signal'",
  "fundamental_bias": "BULLISH_USD | BEARISH_USD | BULLISH_EUR | BEARISH_GBP | NEUTRAL | etc.",
  "veto": true | false,
  "confidence": 0-100
}"""


def _get_session() -> str:
    hour = datetime.now(timezone.utc).hour
    if 0 <= hour < 7:
        return "Asian"
    elif 7 <= hour < 13:
        return "London"
    elif 13 <= hour < 17:
        return "NY_overlap"
    else:
        return "NY"


def _build_payload(pair: str, direction: str, tech: dict, news_summary: str, upcoming_events: str) -> str:
    session = _get_session()
    htf_bias = tech.get("reason", "")
    htf_tag = ""
    if "htf:BULLISH" in htf_bias:
        htf_tag = "HTF (H1) trend: BULLISH"
    elif "htf:BEARISH" in htf_bias:
        htf_tag = "HTF (H1) trend: BEARISH"

    is_counter = (direction == "BUY" and "htf:BEARISH" in htf_bias) or \
                 (direction == "SELL" and "htf:BULLISH" in htf_bias)

    return json.dumps({
        "trade_signal": {
            "pair": pair,
            "direction": direction,
            "strategy": tech.get("strategy", ""),
            "order_type": tech.get("order_type", "MARKET"),
            "technical_confidence": tech.get("confidence", 0),
            "htf_trend": htf_tag or "unknown",
            "is_counter_trend": is_counter,
            "session": session,
        },
        "market_context": {
            "news_summary": news_summary,
            "upcoming_high_impact_events": upcoming_events,
        },
        "task": (
            f"Should this {direction} on {pair} be BLOCKED for fundamental reasons? "
            f"If no specific catalyst exists, APPROVE it (veto: false)."
        ),
    }, indent=2)


async def _call_gemini(payload_text: str) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": payload_text}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": 512,
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=body, params={"key": GEMINI_API_KEY})
        resp.raise_for_status()
        data = resp.json()

    raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()
    return json.loads(raw_text)


async def _call_groq(payload_text: str) -> dict:
    url = "https://api.groq.com/openai/v1/chat/completions"
    body = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": payload_text},
        ],
        "temperature": 0.2,
        "max_tokens": 512,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url, json=body,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        )
        resp.raise_for_status()
        data = resp.json()

    return json.loads(data["choices"][0]["message"]["content"].strip())


async def check_fundamental(
    pair: str,
    direction: str,
    tech_summary: dict,
    news_summary: str = "No recent news available.",
    upcoming_events: str = "No high-impact events in 24h.",
) -> AIFilterResult:
    cache_key = f"{pair}_{direction}"
    now = time.time()

    if cache_key in _cache:
        cached = _cache[cache_key]
        if now - cached["timestamp"] < AI_CACHE_SECONDS:
            r = cached["result"]
            return AIFilterResult(
                veto=r["veto"],
                confidence=r["confidence"],
                fundamental_bias=r["fundamental_bias"],
                reasoning=r["reasoning"],
                cached=True,
            )

    global _rate_limit_until
    if now < _rate_limit_until:
        remaining = int(_rate_limit_until - now)
        # Rate limit → approve (jangan blok trade karena API down)
        return AIFilterResult(
            veto=False, confidence=65,
            fundamental_bias="NEUTRAL",
            reasoning=f"AI rate limit cooldown ({remaining}s) — approving by default",
        )

    payload_text = _build_payload(pair, direction, tech_summary, news_summary, upcoming_events)

    result = None
    for attempt in range(2):
        try:
            if AI_PROVIDER == "gemini":
                result = await _call_gemini(payload_text)
            elif AI_PROVIDER == "groq":
                result = await _call_groq(payload_text)
            else:
                raise ValueError(f"Unknown AI provider: {AI_PROVIDER}")
            break
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                _rate_limit_until = now + 90
            break
        except Exception:
            break

    if result is None:
        # Gagal panggil AI → approve by default (jangan blok trade)
        return AIFilterResult(
            veto=False, confidence=65,
            fundamental_bias="NEUTRAL",
            reasoning="AI call failed — approving by default",
        )

    _cache[cache_key] = {"result": result, "timestamp": now}

    veto      = bool(result.get("veto", False))
    confidence = int(result.get("confidence", 65))

    return AIFilterResult(
        veto=veto,
        confidence=confidence,
        fundamental_bias=result.get("fundamental_bias", "NEUTRAL"),
        reasoning=result.get("reasoning", ""),
    )
