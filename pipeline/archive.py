"""Persistent archive of all stories seen across pipeline runs."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

_FILENAME = "story_archive.json"

# Wire-service and major outlets get higher tier
_HIGH_TIER_SOURCES = {
    "Reuters", "AP News", "BBC News", "NPR", "Al Jazeera",
    "Deutsche Welle", "France 24",
}


def _story_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def _quality_score(story: dict) -> float:
    """Compute a 0-1 quality signal from coverage, source tier, and blurb."""
    score = 0.0
    coverage = story.get("coverage_count", 1)
    if coverage >= 3:
        score += 0.4
    elif coverage >= 2:
        score += 0.2
    if story.get("source") in _HIGH_TIER_SOURCES:
        score += 0.3
    if story.get("blurb"):
        score += 0.3
    return round(min(score, 1.0), 2)


def load(output_dir: str) -> dict:
    """Load the archive, returning the full data dict."""
    path = Path(output_dir).expanduser() / _FILENAME
    if not path.exists():
        return {"version": 1, "stories": []}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or "stories" not in data:
            return {"version": 1, "stories": []}
        return data
    except Exception:
        return {"version": 1, "stories": []}


def save(output_dir: str, archive: dict) -> None:
    """Write the archive to disk."""
    path = Path(output_dir).expanduser() / _FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(archive, indent=2))


def add_stories(archive: dict, stories: list[dict], run_id: str) -> dict:
    """Add new stories to the archive, deduplicating by URL hash."""
    existing_ids = {s["id"] for s in archive["stories"]}
    now = datetime.now(timezone.utc).isoformat()

    for story in stories:
        url = story.get("url", "")
        if not url:
            continue
        sid = _story_id(url)
        if sid in existing_ids:
            continue

        also = story.get("also_covered_by", [])
        coverage_count = 1 + len(also)

        pub = story.get("published")
        if hasattr(pub, "isoformat"):
            pub = pub.isoformat()
        elif pub is None:
            pub = ""

        entry = {
            "id": sid,
            "title": story.get("title", ""),
            "url": url,
            "source": story.get("source", ""),
            "blurb": story.get("blurb", ""),
            "published": pub,
            "seen_at": now,
            "run_id": run_id,
            "topics": story.get("topics", []),
            "also_covered_by": also,
            "coverage_count": coverage_count,
        }
        entry["quality"] = _quality_score(entry)
        archive["stories"].append(entry)
        existing_ids.add(sid)

    return archive
