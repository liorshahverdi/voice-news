"""Merge, deduplicate, and rank stories from all sources."""

import re
from datetime import datetime, timezone

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "it", "as", "by", "be", "was", "are", "from",
    "that", "this", "its", "has", "have", "had", "not", "says", "say",
    "will", "would", "could", "can", "new", "more",
}


def significant_words(title: str) -> set[str]:
    words = re.findall(r"[a-z]+", title.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


# Keep underscore alias for internal use
_significant_words = significant_words


def _key_tokens(title: str) -> set[str]:
    """Proper nouns and numbers — high-signal tokens that fingerprint an event."""
    numbers = set(re.findall(r"\b\d+\b", title))
    # Capitalized words that aren't the first word of the title
    proper = set(re.findall(r"(?<=\s)[A-Z][a-zA-Z]{2,}", title))
    return numbers | {w.lower() for w in proper}


def _find_duplicate(title: str, seen: list[tuple[set, set, dict]]) -> dict | None:
    """Return the surviving story dict if title matches a seen story, else None."""
    sig = _significant_words(title)
    key = _key_tokens(title)
    if not sig:
        return None
    for prev_sig, prev_key, story in seen:
        if not prev_sig:
            continue
        overlap = len(sig & prev_sig) / min(len(sig), len(prev_sig))
        if overlap > 0.6:
            return story
        if key and prev_key and len(key & prev_key) >= 2:
            return story
    return None


def aggregate(
    all_stories: list[list[dict]],
    max_total: int = 20,
) -> list[dict]:
    """Deduplicate and select stories ordered by significance.

    Stories are deduped globally (cross-outlet) via round-robin so no single
    outlet dominates. Result preserves interleaved order — the most important
    story from each outlet surfaces first.
    """
    from collections import defaultdict

    # Bucket by source; sort each bucket by recency or score
    buckets: dict[str, list[dict]] = defaultdict(list)
    for batch in all_stories:
        for story in batch:
            buckets[story["source"]].append(story)

    for source, items in buckets.items():
        if items and items[0].get("published") is not None:
            items.sort(
                key=lambda s: s["published"] or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
        else:
            items.sort(key=lambda s: s.get("score", 0), reverse=True)

    # Round-robin across outlets so no single source dominates dedup
    source_order = list(buckets.keys())
    iterators = {src: iter(items) for src, items in buckets.items()}
    merged = []
    while True:
        added = False
        for src in source_order:
            story = next(iterators[src], None)
            if story:
                merged.append(story)
                added = True
        if not added:
            break

    # Global dedup — duplicates credit their source to the surviving story
    seen: list[tuple[set, set, dict]] = []
    unique = []
    for story in merged:
        survivor = _find_duplicate(story["title"], seen)
        if survivor is None:
            story = dict(story)
            story["also_covered_by"] = []
            seen.append((_significant_words(story["title"]), _key_tokens(story["title"]), story))
            unique.append(story)
            if len(unique) >= max_total:
                break
        else:
            survivor["also_covered_by"].append(story["source"])

    # Sort by significance: stories covered by more outlets rank higher.
    # Within the same coverage count, preserve the original interleaved order
    # (which round-robins across outlets) so no single source like HN
    # dominates due to inflated score values.
    unique.sort(
        key=lambda s: len(s.get("also_covered_by", [])),
        reverse=True,
    )
    return unique
