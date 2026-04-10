"""Extract topic tags from news stories via Ollama."""

import json
import re
import requests

from pipeline.aggregator import significant_words


def _build_prompt(stories: list[dict]) -> str:
    lines = []
    for i, s in enumerate(stories, 1):
        source = s.get("source", "")
        title = s.get("title", "")
        lines.append(f"{i}. [{source}] {title}")
    numbered = "\n".join(lines)
    return (
        "Given these news headlines, assign 1-4 topic tags to each.\n"
        "Use lowercase hyphenated slugs (e.g., \"climate-change\", \"us-politics\").\n"
        "Be consistent across stories. Return ONLY a JSON array of tag lists.\n\n"
        f"{numbered}\n\n"
        "JSON:"
    )


def _parse_response(text: str, count: int) -> list[list[str]] | None:
    """Try to extract a JSON array of tag lists from the LLM response."""
    # Strip markdown code fences if present
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, list) and len(data) == count:
            result = []
            for item in data:
                if isinstance(item, list):
                    tags = [str(t).lower().strip() for t in item[:4]]
                    result.append(tags)
                else:
                    result.append([])
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    # Try to find a JSON array in the text
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list) and len(data) == count:
                result = []
                for item in data:
                    if isinstance(item, list):
                        tags = [str(t).lower().strip() for t in item[:4]]
                        result.append(tags)
                    else:
                        result.append([])
                return result
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _fallback_topics(story: dict) -> list[str]:
    """Extract topic-like tags from the title using significant words."""
    words = significant_words(story.get("title", ""))
    return sorted(words)[:4]


def extract(
    stories: list[dict],
    model: str = "llama3.2:3b",
    host: str = "http://localhost:11434",
) -> list[dict]:
    """Add 'topics' key to each story dict in-place. Returns stories."""
    if not stories:
        return stories

    print(f"[topics] Extracting topics for {len(stories)} stories ({model})...")

    prompt = _build_prompt(stories)
    try:
        payload = {
            "model": model,
            "prompt": prompt,
            "system": "You are a news topic classifier. Return only valid JSON.",
            "stream": False,
        }
        r = requests.post(f"{host}/api/generate", json=payload, timeout=120)
        r.raise_for_status()
        raw = r.json().get("response", "").strip()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        parsed = _parse_response(raw, len(stories))
        if parsed:
            for story, tags in zip(stories, parsed):
                story["topics"] = tags
            print(f"[topics] LLM extraction successful.")
            return stories
        else:
            print("[topics] LLM response could not be parsed, falling back to keywords.")
    except Exception as e:
        print(f"[topics] LLM call failed ({e}), falling back to keywords.")

    # Fallback: keyword extraction
    for story in stories:
        story["topics"] = _fallback_topics(story)
    print(f"[topics] Keyword fallback applied to {len(stories)} stories.")
    return stories
