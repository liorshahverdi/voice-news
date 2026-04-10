"""Generate topic_stats.json from the story archive for the insights dashboard."""

import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

_FILENAME = "topic_stats.json"


def generate(archive: dict, output_dir: str, history_days: int = 90) -> dict:
    """Analyze the archive and write topic_stats.json. Returns the stats dict."""
    stories = archive.get("stories", [])
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=history_days)

    # Filter to history window
    recent = []
    for s in stories:
        try:
            seen = datetime.fromisoformat(s["seen_at"])
            if seen > cutoff:
                recent.append(s)
        except (KeyError, ValueError):
            recent.append(s)

    # --- daily_topics ---
    daily_topics: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: {"count": 0, "sources": set()}))
    for s in recent:
        date = s.get("seen_at", "")[:10]
        if not date:
            continue
        for topic in s.get("topics", []):
            daily_topics[date][topic]["count"] += 1
            daily_topics[date][topic]["sources"].add(s.get("source", ""))

    # Convert sets to sorted lists
    daily_serializable = {}
    for date, topics in sorted(daily_topics.items()):
        daily_serializable[date] = {
            topic: {"count": info["count"], "sources": sorted(info["sources"])}
            for topic, info in topics.items()
        }

    # --- topic_summary ---
    topic_summary: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "first_seen": "", "last_seen": "", "coverage_sum": 0,
    })
    for s in recent:
        for topic in s.get("topics", []):
            ts = topic_summary[topic]
            ts["total"] += 1
            ts["coverage_sum"] += s.get("coverage_count", 1)
            seen_at = s.get("seen_at", "")
            if not ts["first_seen"] or seen_at < ts["first_seen"]:
                ts["first_seen"] = seen_at
            if not ts["last_seen"] or seen_at > ts["last_seen"]:
                ts["last_seen"] = seen_at

    topic_summary_out = {}
    for topic, ts in sorted(topic_summary.items(), key=lambda x: -x[1]["total"]):
        avg_cov = round(ts["coverage_sum"] / ts["total"], 1) if ts["total"] else 0
        topic_summary_out[topic] = {
            "total": ts["total"],
            "first_seen": ts["first_seen"],
            "last_seen": ts["last_seen"],
            "avg_coverage": avg_cov,
        }

    # --- source_topic_matrix ---
    source_topics: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for s in recent:
        src = s.get("source", "")
        for topic in s.get("topics", []):
            source_topics[src][topic] += 1

    source_topic_matrix = {
        src: dict(topics)
        for src, topics in sorted(source_topics.items())
    }

    # --- recent_episodes ---
    episodes: dict[str, dict] = defaultdict(lambda: {"story_count": 0, "topics": defaultdict(int)})
    for s in recent:
        rid = s.get("run_id", "")
        if not rid:
            continue
        episodes[rid]["story_count"] += 1
        for topic in s.get("topics", []):
            episodes[rid]["topics"][topic] += 1

    recent_episodes = []
    for rid, ep in sorted(episodes.items(), reverse=True):
        top = sorted(ep["topics"].items(), key=lambda x: -x[1])[:5]
        recent_episodes.append({
            "run_id": rid,
            "date": rid[:10] if len(rid) >= 10 else rid,
            "story_count": ep["story_count"],
            "top_topics": [t[0] for t in top],
        })

    # --- drift detection ---
    # Compare last 7 days vs prior 21 days
    seven_ago = (now - timedelta(days=7)).isoformat()
    twentyeight_ago = (now - timedelta(days=28)).isoformat()

    recent_7: dict[str, int] = defaultdict(int)
    prior_21: dict[str, int] = defaultdict(int)
    days_recent = 0
    days_prior = 0

    for date_str in sorted(daily_topics.keys()):
        if date_str >= seven_ago[:10]:
            days_recent += 1
            for topic, info in daily_topics[date_str].items():
                recent_7[topic] += info["count"]
        elif date_str >= twentyeight_ago[:10]:
            days_prior += 1
            for topic, info in daily_topics[date_str].items():
                prior_21[topic] += info["count"]

    emerging = []
    fading = []

    if days_recent > 0 and days_prior > 0:
        for topic in set(list(recent_7.keys()) + list(prior_21.keys())):
            recent_avg = recent_7.get(topic, 0) / max(days_recent, 1)
            prior_avg = prior_21.get(topic, 0) / max(days_prior, 1)

            # Emerging: 2x+ increase, at least 2 mentions in recent period
            if recent_avg >= prior_avg * 2 and recent_7.get(topic, 0) >= 2:
                emerging.append(topic)

            # Fading: was active (3+ total) but zero in last 7 days
            total = topic_summary.get(topic, {})
            total_count = total.get("total", 0) if isinstance(total, dict) else 0
            if total_count >= 3 and recent_7.get(topic, 0) == 0:
                fading.append(topic)

    drift = {
        "emerging": sorted(emerging),
        "fading": sorted(fading),
    }

    stats = {
        "generated_at": now.isoformat(),
        "daily_topics": daily_serializable,
        "topic_summary": topic_summary_out,
        "source_topic_matrix": source_topic_matrix,
        "recent_episodes": recent_episodes[:30],
        "drift": drift,
    }

    # Write to output dir
    path = Path(output_dir).expanduser() / _FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2))
    print(f"[insights] Wrote {path} ({len(recent)} stories, {len(topic_summary_out)} topics)")

    return stats
