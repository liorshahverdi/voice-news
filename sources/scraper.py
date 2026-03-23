"""Generic headline scraper — used as fallback when an RSS feed yields nothing."""

import re
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; voice-news/1.0)"})

# Feed-subdomain prefixes to strip when deriving a homepage URL
_FEED_SUBDOMAINS = re.compile(r"^(feeds?|rss|atom)\.", re.I)


def _homepage_from_feed_url(feed_url: str) -> str:
    """Best-effort: turn a feed URL into the site's homepage URL."""
    parsed = urlparse(feed_url)
    host = _FEED_SUBDOMAINS.sub("www.", parsed.netloc)
    return f"{parsed.scheme}://{host}"


def _is_article_url(href: str, base_domain: str) -> bool:
    parsed = urlparse(href)
    if parsed.netloc and parsed.netloc != base_domain:
        return False  # external link
    path = parsed.path.rstrip("/")
    if not path or path in ("", "/"):
        return False  # homepage or empty
    # Looks like an article: has a slug (contains letters) and isn't just a category
    segments = [s for s in path.split("/") if s]
    return len(segments) >= 1 and re.search(r"[a-z]", segments[-1], re.I) is not None


def scrape(homepage: str, source_name: str, max_items: int = 5) -> list[dict]:
    """Scrape headlines from *homepage* and return normalized story dicts."""
    try:
        r = _SESSION.get(homepage, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"[scraper] {source_name}: could not fetch {homepage}: {e}")
        return []

    soup = BeautifulSoup(r.text, "lxml")

    # Strip boilerplate regions that contain non-article links
    for tag in soup(["nav", "footer", "aside", "script", "style"]):
        tag.decompose()

    base_domain = urlparse(homepage).netloc
    candidates: list[dict] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    def _add(title: str, href: str) -> None:
        title = title.strip()
        if not title or len(title) < 25 or len(title) > 250:
            return
        full_url = urljoin(homepage, href)
        if not _is_article_url(full_url, base_domain):
            return
        norm_title = re.sub(r"\s+", " ", title.lower())
        if full_url in seen_urls or norm_title in seen_titles:
            return
        seen_urls.add(full_url)
        seen_titles.add(norm_title)
        candidates.append({
            "title": title,
            "url": full_url,
            "source": source_name,
            "blurb": "",
            "score": 0,
            "published": None,
        })

    # Strategy 1: <a> inside heading tags (most reliable pattern)
    for heading in soup.find_all(["h1", "h2", "h3"]):
        a = heading.find("a", href=True)
        if a:
            _add(a.get_text() or heading.get_text(), a["href"])

    # Strategy 2: <a> with headline/title/story in its class name
    for a in soup.find_all("a", href=True):
        classes = " ".join(a.get("class", []))
        if re.search(r"headline|title|story|article", classes, re.I):
            _add(a.get_text(), a["href"])

    # Strategy 3: prominent links (<a> with substantial text) inside <article>
    for article in soup.find_all("article"):
        for a in article.find_all("a", href=True):
            text = a.get_text().strip()
            if len(text) >= 35:
                _add(text, a["href"])

    if candidates:
        print(f"[scraper] {source_name}: scraped {len(candidates[:max_items])} headlines from {homepage}")
    else:
        print(f"[scraper] {source_name}: no headlines found at {homepage}")

    return candidates[:max_items]
