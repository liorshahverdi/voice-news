"""RSS feed fetcher using requests + feedparser.

Falls back to direct HTML scraping when a feed returns no usable entries.
"""

import re
import feedparser
import requests
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

from sources import scraper as _scraper

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; voice-news/1.0)"})


def _parse_date(entry) -> datetime | None:
    for attr in ("published", "updated"):
        raw = entry.get(attr)
        if raw:
            try:
                return parsedate_to_datetime(raw)
            except Exception:
                pass
    if entry.get("published_parsed"):
        t = entry.published_parsed
        return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def _fetch_feed(name: str, url: str, max_entries: int) -> list[dict]:
    """Fetch a single RSS feed. Returns [] on failure or empty feed."""
    try:
        r = _SESSION.get(url, timeout=8)
        r.raise_for_status()
        parsed = feedparser.parse(r.text)
        stories = []
        for entry in parsed.entries[:max_entries]:
            title = entry.get("title", "").strip()
            if not title:
                continue
            blurb = entry.get("summary", entry.get("description", "")).strip()
            blurb = re.sub(r"<[^>]+>", "", blurb)[:300]
            stories.append({
                "title": title,
                "url": entry.get("link", ""),
                "source": name,
                "blurb": blurb,
                "score": 0,
                "published": _parse_date(entry),
            })
        return stories
    except Exception as e:
        print(f"[rss] Error fetching {name}: {e}")
        return []


def fetch(feeds: list[dict]) -> list[dict]:
    """Fetch all configured RSS feeds, falling back to scraping when empty.

    Each feed dict: {name, url, max, homepage (optional)}
    """
    stories = []
    for feed_cfg in feeds:
        name = feed_cfg["name"]
        url = feed_cfg["url"]
        max_entries = feed_cfg.get("max", 3)

        feed_stories = _fetch_feed(name, url, max_entries)

        if not feed_stories:
            # Derive or use explicit homepage for scrape fallback
            homepage = feed_cfg.get("homepage") or _scraper._homepage_from_feed_url(url)
            feed_stories = _scraper.scrape(homepage, name, max_items=max_entries)

        stories.extend(feed_stories)

    return stories
