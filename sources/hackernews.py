"""Hacker News top stories via Firebase API."""

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

HN_BASE = "https://hacker-news.firebaseio.com/v0"


def _fetch_item(item_id: int) -> dict | None:
    try:
        r = requests.get(f"{HN_BASE}/item/{item_id}.json", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def fetch(max_stories: int = 5) -> list[dict]:
    """Return top HN stories as normalized dicts."""
    r = requests.get(f"{HN_BASE}/topstories.json", timeout=10)
    r.raise_for_status()
    top_ids = r.json()[:30]

    items = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_item, id_): id_ for id_ in top_ids}
        for f in as_completed(futures):
            item = f.result()
            if item and item.get("type") == "story" and item.get("title"):
                items.append(item)

    items.sort(key=lambda x: x.get("score", 0), reverse=True)

    return [
        {
            "title": item["title"],
            "url": item.get("url", f"https://news.ycombinator.com/item?id={item['id']}"),
            "source": "Hacker News",
            "blurb": f"{item.get('score', 0)} points, {item.get('descendants', 0)} comments",
            "score": item.get("score", 0),
            "published": None,
        }
        for item in items[:max_stories]
    ]
