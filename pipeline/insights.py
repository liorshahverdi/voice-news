"""Generate topic_stats.json from the story archive for the insights dashboard."""

import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

_FILENAME = "topic_stats.json"


def generate(archive: dict, output_dir: str, history_days: int = 90,
             model: str = "llama3.2:3b", host: str = "http://localhost:11434") -> dict:
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

    # --- recent_episodes with story detail ---
    recent_episodes = _build_episode_detail(recent)

    # --- drift detection ---
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

            if recent_avg >= prior_avg * 2 and recent_7.get(topic, 0) >= 2:
                emerging.append(topic)

            total = topic_summary.get(topic, {})
            total_count = total.get("total", 0) if isinstance(total, dict) else 0
            if total_count >= 3 and recent_7.get(topic, 0) == 0:
                fading.append(topic)

    drift = {
        "emerging": sorted(emerging),
        "fading": sorted(fading),
    }

    # --- Build stats dict ---
    stats = {
        "generated_at": now.isoformat(),
        "daily_topics": daily_serializable,
        "topic_summary": topic_summary_out,
        "source_topic_matrix": source_topic_matrix,
        "recent_episodes": recent_episodes,
        "drift": drift,
    }

    # --- Quantitative metrics (pure Python, no LLM) ---
    try:
        stats["metrics"] = _compute_quantitative_metrics(
            recent, daily_topics, source_topics, topic_summary_out,
            recent_7, prior_21, now,
        )
    except Exception as e:
        print(f"[insights] Warning: metrics computation failed: {e}")
        stats["metrics"] = {}

    # --- Semantic drift (needs Ollama) ---
    try:
        stats["semantic_drift"] = _compute_semantic_drift(
            recent, now, model, host,
        )
    except Exception as e:
        print(f"[insights] Warning: semantic drift failed: {e}")
        stats["semantic_drift"] = {"tracked_topics": {}}

    # --- Narrative analysis (needs Ollama) ---
    try:
        stats["narrative"] = _generate_narrative_analysis(
            topic_summary_out, drift, stats.get("metrics", {}),
            stats.get("semantic_drift", {}), model, host,
        )
    except Exception as e:
        print(f"[insights] Warning: narrative analysis failed: {e}")
        stats["narrative"] = {}

    # Write to output dir
    path = Path(output_dir).expanduser() / _FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2))
    print(f"[insights] Wrote {path} ({len(recent)} stories, {len(topic_summary_out)} topics)")

    return stats


# ---------------------------------------------------------------------------
# Helper: Ollama call (mirrors narrator.py pattern)
# ---------------------------------------------------------------------------

def _call_ollama(prompt: str, model: str, host: str, system: str = "") -> str:
    payload = {"model": model, "prompt": prompt, "stream": False}
    if system:
        payload["system"] = system
    r = requests.post(f"{host}/api/generate", json=payload, timeout=120)
    r.raise_for_status()
    text = r.json().get("response", "").strip()
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _embed_texts(texts: list[str], model: str, host: str) -> list[list[float]]:
    """Batch-embed texts via Ollama /api/embed."""
    if not texts:
        return []
    r = requests.post(
        f"{host}/api/embed",
        json={"model": model, "input": texts},
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get("embeddings", [])


# ---------------------------------------------------------------------------
# 2b. Narrative analysis
# ---------------------------------------------------------------------------

def _generate_narrative_analysis(topic_summary, drift, metrics, semantic_drift,
                                  model, host) -> dict:
    top_topics = list(topic_summary.keys())[:10]
    emerging = drift.get("emerging", [])[:5]
    fading = drift.get("fading", [])[:5]

    diversity = metrics.get("coverage_diversity", {})
    velocity = metrics.get("topic_velocity", [])[:5]
    drift_topics = semantic_drift.get("tracked_topics", {})

    context = (
        f"Top topics: {', '.join(top_topics)}\n"
        f"Emerging: {', '.join(emerging) or 'none'}\n"
        f"Fading: {', '.join(fading) or 'none'}\n"
        f"Sources active: {diversity.get('source_count', '?')}, "
        f"Topics tracked: {diversity.get('topic_count', '?')}\n"
    )

    if velocity:
        vel_lines = [f"  {v['topic']}: {v['direction']} ({v['velocity']:.1f}x)" for v in velocity]
        context += "Topic velocity (7d vs prior 7d):\n" + "\n".join(vel_lines) + "\n"

    if drift_topics:
        drift_lines = [f"  {t}: drift={d.get('drift_score', 0):.2f}" for t, d in list(drift_topics.items())[:5]]
        context += "Semantic drift:\n" + "\n".join(drift_lines) + "\n"

    system = (
        "You are an analytics narrator for a news insights dashboard. "
        "Write concise, insightful analysis — no markdown, no bullet points. "
        "Respond ONLY with valid JSON, no other text."
    )

    prompt = (
        f"Given this news analytics data:\n{context}\n"
        f"Return a JSON object with exactly these keys:\n"
        f'- "daily_briefing": 2-3 sentences summarizing today\'s news landscape\n'
        f'- "weekly_analysis": 2-3 sentences on this week\'s trends and patterns\n'
        f'- "notable_observation": 1-2 sentences highlighting the single most interesting finding\n'
        f"Return ONLY the JSON object."
    )

    raw = _call_ollama(prompt, model, host, system=system)

    # Try to extract JSON from response
    try:
        # Find JSON object in response
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
        else:
            result = json.loads(raw)
    except json.JSONDecodeError:
        result = {
            "daily_briefing": raw[:500] if raw else "Analysis unavailable.",
            "weekly_analysis": "",
            "notable_observation": "",
        }

    # Ensure all keys exist
    for key in ("daily_briefing", "weekly_analysis", "notable_observation"):
        if key not in result:
            result[key] = ""

    return result


# ---------------------------------------------------------------------------
# 2c. Quantitative metrics
# ---------------------------------------------------------------------------

def _compute_quantitative_metrics(recent, daily_topics, source_topics,
                                   topic_summary_out, recent_7, prior_21,
                                   now) -> dict:
    # --- coverage_diversity ---
    sources = set()
    topics_set = set()
    topic_sources: dict[str, set] = defaultdict(set)

    for s in recent:
        src = s.get("source", "")
        if src:
            sources.add(src)
        for t in s.get("topics", []):
            topics_set.add(t)
            topic_sources[t].add(src)

    source_count = len(sources)
    topic_count = len(topics_set)
    avg_sources_per_topic = (
        round(sum(len(v) for v in topic_sources.values()) / max(len(topic_sources), 1), 2)
    )

    # Gini coefficient of story distribution across sources
    source_story_counts = defaultdict(int)
    for s in recent:
        src = s.get("source", "")
        if src:
            source_story_counts[src] += 1

    gini = _gini_coefficient(list(source_story_counts.values()))

    coverage_diversity = {
        "source_count": source_count,
        "topic_count": topic_count,
        "avg_sources_per_topic": avg_sources_per_topic,
        "gini_coefficient": round(gini, 3),
    }

    # --- topic_velocity ---
    seven_ago = (now - timedelta(days=7)).isoformat()[:10]
    fourteen_ago = (now - timedelta(days=14)).isoformat()[:10]

    stories_7d: dict[str, int] = defaultdict(int)
    stories_prior_7d: dict[str, int] = defaultdict(int)

    for s in recent:
        date = s.get("seen_at", "")[:10]
        if not date:
            continue
        for t in s.get("topics", []):
            if date >= seven_ago:
                stories_7d[t] += 1
            elif date >= fourteen_ago:
                stories_prior_7d[t] += 1

    all_topics = set(list(stories_7d.keys()) + list(stories_prior_7d.keys()))
    velocity_list = []
    for t in all_topics:
        cur = stories_7d.get(t, 0)
        prev = stories_prior_7d.get(t, 0)
        if prev == 0 and cur == 0:
            continue
        velocity = cur / max(prev, 0.5)
        direction = "rising" if velocity > 1.2 else ("falling" if velocity < 0.8 else "stable")
        velocity_list.append({
            "topic": t,
            "velocity": round(velocity, 2),
            "direction": direction,
            "stories_7d": cur,
            "stories_prior_7d": prev,
        })

    velocity_list.sort(key=lambda x: abs(x["velocity"] - 1), reverse=True)
    topic_velocity = velocity_list[:10]

    # --- source_bias_indicators ---
    source_bias = []
    for src, topics_map in source_topics.items():
        if not topics_map:
            continue
        total = sum(topics_map.values())
        dominant = max(topics_map, key=topics_map.get)
        concentration = round(topics_map[dominant] / total, 3) if total else 0
        source_bias.append({
            "source": src,
            "dominant_topic": dominant,
            "concentration": concentration,
            "topic_count": len(topics_map),
        })

    source_bias.sort(key=lambda x: x["concentration"], reverse=True)

    # --- daily_volume ---
    daily_volume = []
    for date in sorted(daily_topics.keys()):
        count = sum(info["count"] for info in daily_topics[date].values())
        daily_volume.append({"date": date, "count": count})

    return {
        "coverage_diversity": coverage_diversity,
        "topic_velocity": topic_velocity,
        "source_bias_indicators": source_bias,
        "daily_volume": daily_volume,
    }


def _gini_coefficient(values: list[int]) -> float:
    """Compute the Gini coefficient for a list of non-negative values."""
    if not values or all(v == 0 for v in values):
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    cumulative = sum((i + 1) * v for i, v in enumerate(sorted_vals))
    total = sum(sorted_vals)
    return (2 * cumulative) / (n * total) - (n + 1) / n


# ---------------------------------------------------------------------------
# 2d. Episode detail
# ---------------------------------------------------------------------------

def _build_episode_detail(recent: list[dict]) -> list[dict]:
    """Build recent episodes with per-story detail."""
    episodes: dict[str, dict] = defaultdict(lambda: {
        "story_count": 0,
        "topics": defaultdict(int),
        "stories": [],
    })

    for s in recent:
        rid = s.get("run_id", "")
        if not rid:
            continue
        ep = episodes[rid]
        ep["story_count"] += 1
        for topic in s.get("topics", []):
            ep["topics"][topic] += 1

        if len(ep["stories"]) < 20:
            ep["stories"].append({
                "title": s.get("title", ""),
                "url": s.get("url", ""),
                "source": s.get("source", ""),
                "topics": s.get("topics", []),
                "also_covered_by": s.get("also_covered_by", []),
                "coverage_count": s.get("coverage_count", 1),
            })

    result = []
    for rid, ep in sorted(episodes.items(), reverse=True):
        top = sorted(ep["topics"].items(), key=lambda x: -x[1])[:5]
        result.append({
            "run_id": rid,
            "date": rid[:10] if len(rid) >= 10 else rid,
            "story_count": ep["story_count"],
            "top_topics": [t[0] for t in top],
            "stories": ep["stories"],
        })
        if len(result) >= 14:
            break

    return result


# ---------------------------------------------------------------------------
# 2e. Semantic drift
# ---------------------------------------------------------------------------

def _compute_semantic_drift(recent, now, model, host) -> dict:
    """Compute semantic drift for top topics using embeddings."""
    seven_ago = (now - timedelta(days=7)).isoformat()[:10]
    twentyeight_ago = (now - timedelta(days=28)).isoformat()[:10]

    # Group headlines by topic and time window
    topic_recent: dict[str, list[str]] = defaultdict(list)
    topic_prior: dict[str, list[str]] = defaultdict(list)

    for s in recent:
        date = s.get("seen_at", "")[:10]
        title = s.get("title", "")
        if not date or not title:
            continue
        for t in s.get("topics", []):
            if date >= seven_ago:
                topic_recent[t].append(title)
            elif date >= twentyeight_ago:
                topic_prior[t].append(title)

    # Find topics with data in both windows
    shared_topics = [
        t for t in topic_recent
        if t in topic_prior and len(topic_recent[t]) >= 2 and len(topic_prior[t]) >= 2
    ]

    # Sort by total headlines, take top 10
    shared_topics.sort(key=lambda t: len(topic_recent[t]) + len(topic_prior[t]), reverse=True)
    shared_topics = shared_topics[:10]

    if not shared_topics:
        return {"tracked_topics": {}}

    # Collect all headlines for batch embedding
    all_texts = []
    text_map = []  # (topic, window, index_in_topic_list)

    for t in shared_topics:
        for headline in topic_recent[t][:10]:
            text_map.append((t, "recent", len(all_texts)))
            all_texts.append(headline)
        for headline in topic_prior[t][:10]:
            text_map.append((t, "prior", len(all_texts)))
            all_texts.append(headline)

    # Batch embed
    embeddings = _embed_texts(all_texts, model, host)
    if not embeddings or len(embeddings) != len(all_texts):
        return {"tracked_topics": {}}

    # Compute centroids and drift per topic
    tracked = {}
    high_drift_topics = []

    for t in shared_topics:
        recent_embs = [embeddings[i] for topic, window, i in text_map if topic == t and window == "recent"]
        prior_embs = [embeddings[i] for topic, window, i in text_map if topic == t and window == "prior"]

        if not recent_embs or not prior_embs:
            continue

        recent_centroid = _centroid(recent_embs)
        prior_centroid = _centroid(prior_embs)
        drift_score = 1 - _cosine_sim(recent_centroid, prior_centroid)
        drift_score = round(max(0, min(1, drift_score)), 4)

        direction = "shifting" if drift_score > 0.1 else "stable"

        tracked[t] = {
            "drift_score": drift_score,
            "drift_direction": direction,
            "recent_headlines": topic_recent[t][:5],
            "prior_headlines": topic_prior[t][:5],
        }

        if drift_score > 0.1:
            high_drift_topics.append(t)

    # Generate explanations for high-drift topics
    if high_drift_topics:
        for t in high_drift_topics[:5]:
            try:
                info = tracked[t]
                prompt = (
                    f"Topic: {t}\n"
                    f"Recent headlines: {'; '.join(info['recent_headlines'][:3])}\n"
                    f"Older headlines: {'; '.join(info['prior_headlines'][:3])}\n"
                    f"In one sentence, describe how coverage of '{t}' has shifted."
                )
                explanation = _call_ollama(prompt, model, host)
                tracked[t]["drift_explanation"] = explanation
            except Exception:
                tracked[t]["drift_explanation"] = ""

    return {"tracked_topics": tracked}


def _centroid(vectors: list[list[float]]) -> list[float]:
    """Compute element-wise mean of vectors."""
    if not vectors:
        return []
    dim = len(vectors[0])
    result = [0.0] * dim
    for v in vectors:
        for i in range(dim):
            result[i] += v[i]
    n = len(vectors)
    return [x / n for x in result]


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
