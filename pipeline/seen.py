"""Persistent store of previously reported article URLs."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

_FILENAME = "seen_articles.json"
_EXPIRY_DAYS = 30


def _state_path(output_dir: str) -> Path:
    return Path(output_dir).expanduser() / _FILENAME


def load(output_dir: str) -> set[str]:
    """Return set of URLs seen within the expiry window."""
    path = _state_path(output_dir)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text())
        cutoff = datetime.now(timezone.utc) - timedelta(days=_EXPIRY_DAYS)
        return {
            entry["url"]
            for entry in data
            if datetime.fromisoformat(entry["seen_at"]) > cutoff
        }
    except Exception:
        return set()


def save(output_dir: str, new_urls: list[str]) -> None:
    """Append new_urls to the state file, pruning entries older than expiry."""
    path = _state_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            existing = []

    cutoff = datetime.now(timezone.utc) - timedelta(days=_EXPIRY_DAYS)
    pruned = [
        e for e in existing
        if datetime.fromisoformat(e["seen_at"]) > cutoff
    ]

    now = datetime.now(timezone.utc).isoformat()
    existing_urls = {e["url"] for e in pruned}
    for url in new_urls:
        if url and url not in existing_urls:
            pruned.append({"url": url, "seen_at": now})

    path.write_text(json.dumps(pruned, indent=2))
