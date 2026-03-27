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
    "When a story is marked '[also covered by: X, Y]', weave that in naturally — "
    "like 'CNN and NBC are both reporting that...' or 'Both the BBC and Reuters have this one...'. "
    "Mention the outlet each story comes from naturally in context — "
    "e.g. 'According to Reuters...' or 'The Guardian is reporting...' — "
    "but do NOT group stories by outlet or announce outlets as sections. "
    "Cover all topics objectively: politics, world affairs, business, science, tech, culture — "
    "do not favor or lead with any particular topic area. "
    "The stories are already ordered from most significant to least significant — "
    "follow that order, giving the biggest stories more weight. "
    "Do not use section headers, bullet points, or markdown. "
    "Do not ask questions or offer further assistance. "
    "Do not use stage directions, parenthetical notations, or tone indicators such as "
    "(sigh), (concerned tone), or similar — express emotion through word choice alone."
)


def _story_lines(items: list[dict]) -> str:
    lines = []
    for i, item in enumerate(items, 1):
        blurb = item.get("blurb", "")
        blurb_part = f" — {blurb}" if blurb else ""
        also = item.get("also_covered_by", [])
        also_part = f" [also covered by: {', '.join(also)}]" if also else ""
        source = item.get("source", "")
        lines.append(f"{i}. [{source}] {item['title']}{blurb_part}{also_part}")
    return "\n".join(lines)


def _call_ollama(system: str, prompt: str, model: str, host: str) -> str:
    payload = {"model": model, "system": system, "prompt": prompt, "stream": False}
    r = requests.post(f"{host}/api/generate", json=payload, timeout=300)
    r.raise_for_status()
    text = r.json().get("response", "").strip()
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def generate(stories: list[dict], model: str = "llama3.2:3b", host: str = "http://localhost:11434") -> str:
    """Generate the briefing as a single unified script ordered by significance."""
    print(f"[narrator] Generating briefing for {len(stories)} stories ({model})...")

    # Split into chunks — smaller chunks yield more detailed coverage per story
    chunk_size = 5
    chunks = [stories[i:i + chunk_size] for i in range(0, len(stories), chunk_size)]

    try:
        segments = []
        for i, chunk in enumerate(chunks):
            is_first = i == 0
            is_last = i == len(chunks) - 1

            coverage_instruction = (
                f"For each story, first relay the key details as reported by the original outlet "
                f"in 3-4 sentences — what happened, who's involved, and why it matters — "
                f"then add 1-2 sentences of your own natural reaction or context. "
            )

            if is_first and is_last:
                prompt = (
                    f"Open with one sentence that honestly captures the feel of today's news, "
                    f"then cover each of these {len(chunk)} stories — they're ranked from most significant to least. "
                    f"{coverage_instruction}"
                    f"Mention each story's outlet naturally. Weave related stories together, don't just list them. "
                    f"Do not sign off — the conclusion comes separately.\n\n"
                    f"{_story_lines(chunk)}"
                )
            elif is_first:
                prompt = (
                    f"Open with one sentence that honestly captures the feel of today's news, "
                    f"then cover each of these {len(chunk)} stories — they're ranked from most significant to least. "
                    f"{coverage_instruction}"
                    f"Mention each story's outlet naturally. Weave related stories together, don't just list them. "
                    f"Do not sign off — more stories are coming.\n\n"
                    f"{_story_lines(chunk)}"
                )
            elif is_last:
                prompt = (
                    f"Continue the briefing naturally with these {len(chunk)} remaining stories. "
                    f"{coverage_instruction}"
                    f"Mention each story's outlet naturally. Weave related stories together, don't just list them. "
                    f"Do not sign off — the conclusion comes separately.\n\n"
                    f"{_story_lines(chunk)}"
                )
            else:
                prompt = (
                    f"Continue the briefing naturally with these {len(chunk)} stories. "
                    f"{coverage_instruction}"
                    f"Mention each story's outlet naturally. Weave related stories together, don't just list them. "
                    f"Do not sign off — more stories are coming.\n\n"
                    f"{_story_lines(chunk)}"
                )

            print(f"[narrator]   chunk {i + 1}/{len(chunks)} ({len(chunk)} stories)...")
            segment = _call_ollama(_SYSTEM_PROMPT, prompt, model, host)
            if segment:
                segments.append(segment)

        # Generate a reflective conclusion that ties back to the major stories
        top_stories = stories[:5]
        conclusion_prompt = (
            f"You've just finished covering today's news. Here are the biggest stories you reported on:\n\n"
            f"{_story_lines(top_stories)}\n\n"
            f"Now wrap up the briefing with 3-4 sentences that reflect on the day's major themes — "
            f"what connects these stories, what they say about where things are headed, "
            f"or what stuck with you most. Be genuine and thoughtful, not generic. "
            f"Then close with a warm, definitive sign-off in one sentence — e.g. "
            f"'That's your news for today, thanks for listening.' or 'Take care of yourselves out there.' "
            f"Do NOT trail off, tease future content, or leave anything open-ended. "
            f"The last sentence must feel like a definitive goodbye."
        )
        print(f"[narrator]   generating conclusion...")
        conclusion = _call_ollama(_SYSTEM_PROMPT, conclusion_prompt, model, host)
        if conclusion:
            segments.append(conclusion)

        script = "\n\n".join(segments)
        date_str = datetime.now().strftime("%A, %B %-d, %Y")
        intro = f"Hi, I'm Emma. Today is {date_str}. And this is Voice News."
        return f"{intro}\n\n{script}"

    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Could not connect to Ollama at {host}. "
            "Make sure Ollama is running: `ollama serve`"
        )
