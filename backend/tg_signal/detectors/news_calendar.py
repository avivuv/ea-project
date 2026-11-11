"""
Forex Factory economic calendar via official XML feed.
URL: https://nfs.faireconomy.media/ff_calendar_thisweek.xml
Struktur event: <title>, <country>, <impact>, <date>, <time>
Cache 30 menit.
"""
from __future__ import annotations

import asyncio
import time
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

import httpx

log = logging.getLogger(__name__)

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
CACHE_SECONDS = 3600  # 1 jam

_cache: dict = {}  # {"events": [...], "timestamp": float}
_fetch_lock = asyncio.Lock()

PAIR_CURRENCIES = {
    "EURUSD": {"EUR", "USD"},
    "GBPUSD": {"GBP", "USD"},
    "USDJPY": {"USD", "JPY"},
    "XAUUSD": {"USD"},
    "US500":  {"USD"},
    "USTEC":  {"USD"},
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _parse_xml(xml_text: str) -> list[dict]:
    """Parse FF XML feed, return list event HIGH impact saja."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning(f"[ForexCalendar] XML parse error: {exc}")
        return []

    events: list[dict] = []
    for event in root.findall("event"):
        impact = (event.findtext("impact") or "").strip().upper()
        if impact != "HIGH":
            continue

        title    = (event.findtext("title")   or "").strip()
        country  = (event.findtext("country") or "").strip().upper()
        date_str = (event.findtext("date")    or "").strip()
        time_str = (event.findtext("time")    or "").strip()

        if not title or not country or not date_str:
            continue

        events.append({
            "title":   title,
            "country": country,
            "date":    date_str,
            "time":    time_str,
        })

    return events


async def _fetch_events() -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as client:
            resp = await client.get(FEED_URL)
            resp.raise_for_status()
        events = _parse_xml(resp.text)
        log.info(f"[ForexCalendar] fetched {len(events)} HIGH-impact events from XML feed")
        return events
    except Exception as exc:
        log.warning(f"[ForexCalendar] fetch failed: {exc}")
        return []


def _is_within_window(date_str: str, time_str: str, hours_ahead: int = 4) -> bool:
    """
    Return True jika event dalam rentang -1 jam s/d +N jam dari sekarang (UTC).
    FF XML format: date='MM-DD-YYYY', time='H:MMam' atau 'All Day' / 'Tentative'.
    """
    try:
        dt = datetime.strptime(date_str, "%m-%d-%Y")
        time_str_clean = time_str.strip().lower()
        if time_str_clean in ("all day", "tentative", ""):
            event_dt = dt.replace(tzinfo=timezone.utc)
        else:
            try:
                t = datetime.strptime(time_str_clean, "%I:%M%p")
            except ValueError:
                t = datetime.strptime(time_str_clean, "%I%p")
            event_dt = dt.replace(hour=t.hour, minute=t.minute, tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        return (now - timedelta(hours=1)) <= event_dt <= (now + timedelta(hours=hours_ahead))
    except Exception:
        return False


async def get_upcoming_events(pair: str) -> str:
    """
    Return string high-impact events untuk pair dalam ~24 jam ke depan.
    Cache 1 jam. Lock mencegah concurrent fetch dari 6 pair sekaligus.
    """
    now = time.time()
    if _cache.get("events") is not None and now - _cache.get("timestamp", 0) < CACHE_SECONDS:
        all_events: list[dict] = _cache["events"]
    else:
        async with _fetch_lock:
            # Re-check setelah lock acquired (mungkin sudah di-fetch oleh coroutine lain)
            now = time.time()
            if _cache.get("events") is not None and now - _cache.get("timestamp", 0) < CACHE_SECONDS:
                all_events = _cache["events"]
            else:
                fetched = await _fetch_events()
                if fetched:
                    _cache["events"] = fetched
                    _cache["timestamp"] = now
                elif _cache.get("events") is not None:
                    # Fetch gagal tapi ada data lama — pakai data lama, update timestamp
                    log.warning("[ForexCalendar] fetch failed, using stale cache")
                    _cache["timestamp"] = now
                else:
                    _cache["events"] = []
                    _cache["timestamp"] = now
                all_events = _cache.get("events", [])

    if not all_events:
        return "No high-impact events data available (calendar fetch failed)."

    currencies = PAIR_CURRENCIES.get(pair.upper(), {"USD"})

    relevant = [
        e for e in all_events
        if e["country"] in currencies and _is_within_window(e["date"], e["time"], hours_ahead=4)
    ]

    if not relevant:
        return f"No HIGH-impact events for {pair} currencies in the next 4h."

    lines = [f"HIGH-IMPACT events for {pair} (next 4h):"]
    for e in relevant[:5]:
        lines.append(f"  [{e['country']}] {e['time']} {e['date']} — {e['title']}")
    return "\n".join(lines)
