# voice-news

A local, privacy-first spoken news briefing. Pulls headlines from RSS feeds, Hacker News, and Reddit, deduplicates cross-outlet stories, writes a podcast-style script with a local LLM, and reads it aloud using on-device TTS — no cloud APIs required.

## How it works

```
RSS feeds ─┐
Hacker News ┼─► Aggregate & deduplicate ─► LLM script (Ollama) ─► TTS (Kokoro) ─► WAV
Reddit     ─┘
```

1. **Fetch** — sources are pulled concurrently
2. **Filter** — articles reported in the past 30 days are skipped
3. **Deduplicate** — cross-outlet stories are merged; the same event reported by multiple outlets is noted as *"CNN and NBC are both reporting that..."* and told once
4. **Narrate** — Ollama generates a segment per outlet, stitched into a single briefing hosted by Emma
5. **Synthesise** — Kokoro TTS converts the script to a WAV file
6. **Play** — audio is played immediately (macOS `afplay`)

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | |
| [Ollama](https://ollama.com) | Running locally — `ollama serve` |
| An Ollama model | Default: `llama3.2:3b` — pull with `ollama pull llama3.2:3b` |
| Kokoro TTS | Installed via `requirements.txt` |

Reddit is optional. Leave the credentials blank in `config.yaml` to skip it.

## Installation

```bash
git clone https://github.com/yourname/voice-news.git
cd voice-news

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp config.example.yaml config.yaml
# edit config.yaml to taste
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and adjust as needed. The file is self-documented with inline comments.

Key sections:

| Section | Purpose |
|---|---|
| `ollama` | Model name and host for the local LLM |
| `rss_feeds` | List of RSS feeds — add, remove, or adjust `max` per outlet |
| `reddit` | Optional PRAW credentials and subreddits |
| `hackernews` | Number of top HN stories to include |
| `tts.voice` | Kokoro voice ID (see voices below) |
| `output_dir` | Where WAV files and article history are saved |
| `max_stories_total` | Cap on stories passed to the LLM |

### Adding an RSS feed

Add an entry under `rss_feeds` in `config.yaml`:

```yaml
rss_feeds:
  - name: "My Feed"
    url: "https://example.com/feed.rss"
    max: 3                                # max headlines to pull from this feed
    homepage: "https://example.com"       # optional fallback for scraping
```

If a feed returns no entries, the scraper will attempt to extract headlines directly from the `homepage` URL.

### Voices

Kokoro voice IDs follow the pattern `{lang}_{name}`. Common options:

| ID | Description |
|---|---|
| `bf_emma` | British female — Emma (default) |
| `bf_alice` | British female — Alice |
| `am_michael` | American male — Michael |
| `am_adam` | American male — Adam |
| `af_sky` | American female — Sky |

## Usage

```bash
# Full pipeline — fetch, narrate, synthesise, and play
python main.py

# Print the script only, no TTS
python main.py --dry-run

# Use a different config file
python main.py --config my_config.yaml

# Synthesise but do not auto-play
python main.py --no-play

# Override output directory
python main.py --output-dir /tmp/news
```

Output WAV files are saved to `output_dir` as `digest_YYYY-MM-DD_HHMMSS.wav`.

Previously reported article URLs are stored in `seen_articles.json` inside `output_dir` and expire after 30 days, so each day's briefing contains only fresh stories.

## Project structure

```
voice-news/
├── main.py                 # Entry point and pipeline orchestration
├── config.example.yaml     # Configuration template
├── requirements.txt
├── pipeline/
│   ├── aggregator.py       # Deduplication and story ranking
│   ├── narrator.py         # LLM script generation (Ollama)
│   ├── seen.py             # Persistent article URL history
│   └── tts.py              # Kokoro TTS synthesis
└── sources/
    ├── hackernews.py       # Hacker News via Firebase API
    ├── reddit.py           # Reddit via PRAW
    ├── rss.py              # RSS feed fetcher
    └── scraper.py          # HTML headline scraper (RSS fallback)
```

## License

MIT
