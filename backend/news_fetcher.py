"""
News fetcher — sumber utama: Investing.com RSS feeds (gratis, pair-specific).
Fallback: NewsAPI top-headlines jika RSS diblok.
"""
import os
import time
import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

import httpx
from dotenv import load_dotenv
from forex_calendar import get_upcoming_events

load_dotenv()

NEWS_API_KEY  = os.getenv("NEWS_API_KEY", "")
CACHE_SECONDS = 1800  # 30 menit — berita lebih fresh dari sebelumnya (1 jam)

_cache: dict[str, dict] = {}

# Browser-like headers agar tidak diblok Investing.com
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Investing.com RSS feed IDs (verified accessible)
# 1=Forex News, 11=Commodities & Futures, 25=Stock Market,
# 95=Economic Indicators, 285=Most Popular, 301=Cryptocurrency
_RSS_BASE = "https://www.investing.com/rss/news_{}.rss"

# Feed yang relevan per pair (urutan = prioritas)
PAIR_FEEDS = {
    "EURUSD": [1, 95],         # Forex + Economic Indicators
    "GBPUSD": [1, 95],
    "USDJPY": [1, 95],
    "EURCHF": [1, 95],
    "XAUUSD": [11, 1, 95],     # Commodities + Forex + Economic Indicators
    "US500":  [25, 95],        # Stock Market + Economic Indicators
    "USTEC":  [25, 95],
    "BTCUSD": [301, 1],        # Cryptocurrency + Forex
}

# Keyword filter per pair (lowercase)
PAIR_KEYWORDS = {
    "EURUSD": ["euro", "eur", "ecb", "european central bank", "dollar", "usd", "fed", "fomc"],
    "GBPUSD": ["pound", "sterling", "gbp", "bank of england", "boe", "dollar", "usd", "uk"],
    "USDJPY": ["yen", "jpy", "bank of japan", "boj", "dollar", "usd", "intervention"],
    "EURCHF": ["euro", "eur", "ecb", "swiss", "snb", "franc", "chf"],
    "XAUUSD": ["gold", "xau", "fed", "rate", "inflation", "safe haven", "yields", "treasury"],
    "US500":  ["s&p", "s&p 500", "sp500", "stock", "fed", "rate", "gdp", "recession", "economy", "earnings"],
    "USTEC":  ["nasdaq", "tech", "fed", "rate", "recession", "economy", "earnings", "ai"],
    "BTCUSD": ["bitcoin", "btc", "crypto", "digital asset", "blockchain"],
}

# Fallback NewsAPI keywords jika RSS gagal
PAIR_NEWSAPI_QUERY = {
    "EURUSD": "euro ECB dollar Fed",
    "GBPUSD": "pound sterling 'Bank of England' dollar",
    "USDJPY": "yen 'Bank of Japan' dollar",
    "XAUUSD": "gold 'Federal Reserve' inflation 'safe haven'",
    "US500":  "S&P 500 'stock market' Fed 'interest rate'",
    "USTEC":  "Nasdaq tech Fed 'interest rate'",
    "BTCUSD": "bitcoin crypto",
    "EURCHF": "euro ECB 'Swiss National Bank' franc",
}


def _parse_rss(xml_text: str) -> list[dict]:
    """Parse RSS XML, return list of {title, description, pub_date}."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items = []
    # Handle both RSS 2.0 (<channel><item>) and Atom-like structures
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        desc  = (item.findtext("description") or "").strip()
        pub   = (item.findtext("pubDate") or "").strip()
        if title and "[Removed]" not in title:
            items.append({"title": title, "description": desc, "pub_date": pub})

    return items


def _is_recent(pub_date_str: str, hours: int = 12) -> bool:
    """Return True jika berita dalam N jam terakhir."""
    if not pub_date_str:
        return True  # Tidak ada timestamp → anggap valid
    try:
        # RFC 2822 format: "Mon, 19 May 2026 08:30:00 +0000"
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(pub_date_str)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return dt >= cutoff
    except Exception:
        return True


def _filter_relevant(items: list[dict], keywords: list[str]) -> list[str]:
    """Filter items by keywords, return formatted headline strings."""
    results = []
    for item in items:
        text = (item["title"] + " " + item["description"]).lower()
        if any(kw in text for kw in keywords):
            if _is_recent(item["pub_date"], hours=12):
                results.append(f"- {item['title']}")
    return results


async def _fetch_investing_rss(feed_ids: list[int], keywords: list[str]) -> str:
    """Fetch RSS dari Investing.com, filter keyword, return formatted string."""
    all_items: list[dict] = []

    async with httpx.AsyncClient(timeout=12, headers=_HEADERS, follow_redirects=True) as client:
        tasks = [client.get(_RSS_BASE.format(fid)) for fid in feed_ids]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    for resp in responses:
        if isinstance(resp, Exception):
            continue
        try:
            resp.raise_for_status()
            all_items.extend(_parse_rss(resp.text))
        except Exception:
            continue

    if not all_items:
        return ""  # Semua feed gagal

    relevant = _filter_relevant(all_items, keywords)

    if relevant:
        return "\n".join(relevant[:5])

    # Tidak ada yang match keyword → ambil 3 headline terbaru sebagai fallback
    recent = [
        f"- {it['title']}"
        for it in all_items
        if _is_recent(it["pub_date"], hours=6)
    ][:3]

    if recent:
        return "Recent market headlines (no direct pair-specific news):\n" + "\n".join(recent)

    return ""


async def _fetch_newsapi_fallback(query: str) -> str:
    """Fallback ke NewsAPI jika Investing.com RSS tidak accessible."""
    if not NEWS_API_KEY:
        return "No news source available."
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://newsapi.org/v2/top-headlines",
                params={"category": "business", "language": "en",
                        "pageSize": 10, "apiKey": NEWS_API_KEY},
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])

        keywords = [k.strip().lower() for k in query.split()]
        relevant = []
        for a in articles:
            title = (a.get("title") or "").lower()
            if any(kw in title for kw in keywords):
                t = (a.get("title") or "").strip()
                if t and "[Removed]" not in t:
                    relevant.append(f"- {t}")
        if relevant:
            return "\n".join(relevant[:4])
        return "No relevant market news found (NewsAPI fallback)."
    except Exception as e:
        return f"News unavailable: {e}"


async def get_news_context(pair: str) -> tuple[str, str]:
    """Return (news_summary, upcoming_events) untuk pair tertentu. Cache 30 menit."""
    now = time.time()
    cached = _cache.get(pair)
    if cached and now - cached["timestamp"] < CACHE_SECONDS:
        return cached["summary"], cached["upcoming"]

    pair_upper = pair.upper()
    feed_ids   = PAIR_FEEDS.get(pair_upper, [285, 14])
    keywords   = PAIR_KEYWORDS.get(pair_upper, ["forex", "dollar", "fed", "rate"])

    # Coba Investing.com RSS dulu
    summary = await _fetch_investing_rss(feed_ids, keywords)

    # Fallback ke NewsAPI jika RSS kosong
    if not summary:
        fallback_query = PAIR_NEWSAPI_QUERY.get(pair_upper, "forex economy")
        summary = await _fetch_newsapi_fallback(fallback_query)

    upcoming = await get_upcoming_events(pair)

    _cache[pair] = {"summary": summary, "upcoming": upcoming, "timestamp": now}
    return summary, upcoming
