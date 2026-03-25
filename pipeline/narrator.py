"""Generate a podcast-style news briefing script via Ollama."""

import re
import requests
from datetime import datetime

_SYSTEM_PROMPT = (
    "You are Emma — the host of a daily news podcast. "
    "You are warm, curious, and genuinely engaged with the stories you cover. "
    "You care about the people behind the headlines, not just the events. "
    "You react authentically: when something is troubling you let that land, "
    "when something is surprising you say so, when something is hopeful you mean it. "
    "Talk the way a trusted friend does: contractions, natural asides, real reactions. "
    "Always sound like a person who has actually read the story. "
    "When a story is marked '[also covered by: X, Y]', open it with a natural phrase "
    "like 'CNN and NBC are both reporting that...' or 'Both the BBC and Reuters have this one...'. "
    "Do not use section headers, bullet points, or markdown. "
    "Do not ask questions or offer further assistance. "
    "Do not use stage directions, parenthetical notations, or tone indicators such as "
    "(sigh), (concerned tone), or similar — express emotion through word choice alone."
)


def _story_lines(items: list[dict]) -> str:
    lines = []
    for item in items:
        blurb = item.get("blurb", "")
        blurb_part = f" — {blurb}" if blurb else ""
        also = item.get("also_covered_by", [])
        also_part = f" [also covered by: {', '.join(also)}]" if also else ""
        lines.append(f"• {item['title']}{blurb_part}{also_part}")
    return "\n".join(lines)


def _call_ollama(system: str, prompt: str, model: str, host: str) -> str:
    payload = {"model": model, "system": system, "prompt": prompt, "stream": False}
    r = requests.post(f"{host}/api/generate", json=payload, timeout=300)
    r.raise_for_status()
    text = r.json().get("response", "").strip()
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _sources_in_order(stories: list[dict]) -> list[str]:
    seen = set()
    order = []
    for s in stories:
        if s["source"] not in seen:
            seen.add(s["source"])
            order.append(s["source"])
    return order


def generate(stories: list[dict], model: str = "llama3.2:3b", host: str = "http://localhost:11434") -> str:
    """Generate the briefing one outlet at a time and stitch the segments together."""
    # Group stories by source, preserving outlet order
    by_source: dict[str, list[dict]] = {}
    for s in stories:
        by_source.setdefault(s["source"], []).append(s)

    sources = _sources_in_order(stories)
    print(f"[narrator] Generating briefing for {len(stories)} stories across {len(sources)} outlets ({model})...")

    try:
        segments = []
        for i, source in enumerate(sources):
            items = by_source[source]
            is_first = i == 0
            is_last = i == len(sources) - 1

            if is_first:
                prompt = (
                    f"Open with one sentence that honestly captures the feel of today's news, "
                    f"then transition naturally into {source}'s stories "
                    f"(e.g. 'Starting with {source}...' or '{source} is leading with...'). "
                    f"Cover the stories below in 2-4 sentences — weave them together, don't list them.\n\n"
                    f"{_story_lines(items)}"
                )
            elif is_last:
                prompt = (
                    f"Transition naturally into {source}'s stories "
                    f"(e.g. 'Over at {source}...' or 'And finally, {source}...'). "
                    f"Cover the stories below in 2-4 sentences — weave them together, don't list them. "
                    f"Then end with a complete, warm sign-off in one sentence — e.g. "
                    f"'That's your news for today, thanks for listening.' "
                    f"Do NOT trail off, tease future content, or leave anything open-ended. "
                    f"The last sentence must feel like a definitive goodbye.\n\n"
                    f"{_story_lines(items)}"
                )
            else:
                prompt = (
                    f"Transition naturally into {source}'s stories "
                    f"(e.g. 'Over at {source}...' or 'Meanwhile, {source}...'). "
                    f"Cover the stories below in 2-4 sentences — weave them together, don't list them.\n\n"
                    f"{_story_lines(items)}"
                )

            print(f"[narrator]   {i + 1}/{len(sources)} {source}...")
            segment = _call_ollama(_SYSTEM_PROMPT, prompt, model, host)
            if segment:
                segments.append(segment)

        script = "\n\n".join(segments)
        date_str = datetime.now().strftime("%A, %B %-d, %Y")
        intro = f"Hi, I'm Emma. Today is {date_str}. And this is Voice News."
        return f"{intro}\n\n{script}"

    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Could not connect to Ollama at {host}. "
            "Make sure Ollama is running: `ollama serve`"
        )
