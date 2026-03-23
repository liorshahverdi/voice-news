#!/usr/bin/env python3
"""
voice-news — local spoken news briefing.

Usage:
  python main.py                  # full pipeline → WAV
  python main.py --dry-run        # print Jarvis script only, no TTS
  python main.py --config custom.yaml
"""

import argparse
import subprocess
import sys
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from sources import hackernews, reddit, rss
from pipeline import aggregator, narrator, tts, seen


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def fetch_all_sources(cfg: dict) -> list[list[dict]]:
    """Fetch all sources concurrently."""
    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {}

        # Hacker News
        hn_cfg = cfg.get("hackernews", {})
        futures[pool.submit(hackernews.fetch, hn_cfg.get("max_stories", 5))] = "hackernews"

        # Reddit
        rd_cfg = cfg.get("reddit", {})
        futures[pool.submit(
            reddit.fetch,
            rd_cfg.get("client_id", ""),
            rd_cfg.get("client_secret", ""),
            rd_cfg.get("user_agent", "voice-news/1.0"),
            rd_cfg.get("subreddits", []),
            rd_cfg.get("max_posts", 5),
        )] = "reddit"

        # RSS feeds
        rss_feeds = cfg.get("rss_feeds", [])
        futures[pool.submit(rss.fetch, rss_feeds)] = "rss"

        for f in as_completed(futures):
            source = futures[f]
            try:
                batch = f.result()
                print(f"[{source}] Fetched {len(batch)} stories.")
                results.append(batch)
            except Exception as e:
                print(f"[{source}] Error: {e}", file=sys.stderr)
                errors.append(source)

    return results


def main():
    parser = argparse.ArgumentParser(description="Jarvis news digest")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--output-dir", default=None, help="Override output directory")
    parser.add_argument("--dry-run", action="store_true", help="Print script, skip TTS")
    parser.add_argument("--no-play", action="store_true", help="Skip audio playback after synthesis")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    cfg = load_config(str(config_path))
    output_dir = args.output_dir or cfg.get("output_dir", "~/voice-news")
    max_total = cfg.get("max_stories_total", 20)

    # 1. Fetch
    print("\n=== Fetching news sources ===")
    all_batches = fetch_all_sources(cfg)

    # 2. Filter previously seen articles
    output_dir = str(Path(output_dir).expanduser())
    seen_urls = seen.load(output_dir)
    if seen_urls:
        before = sum(len(b) for b in all_batches)
        all_batches = [
            [s for s in batch if s.get("url") not in seen_urls]
            for batch in all_batches
        ]
        after = sum(len(b) for b in all_batches)
        print(f"[seen] Filtered {before - after} previously reported articles ({after} remaining).")

    # 3. Aggregate
    print("\n=== Aggregating stories ===")
    stories = aggregator.aggregate(all_batches, max_total=max_total)
    print(f"[aggregator] {len(stories)} unique stories selected.")

    if not stories:
        print("No stories fetched. Check your network / config.", file=sys.stderr)
        sys.exit(1)

    # 4. Narrate
    print("\n=== Generating Jarvis script ===")
    ollama_cfg = cfg.get("ollama", {})
    script = narrator.generate(
        stories,
        model=ollama_cfg.get("model", "llama3.2:3b"),
        host=ollama_cfg.get("host", "http://localhost:11434"),
    )

    print("\n--- Jarvis Script ---")
    print(script)
    print("---------------------\n")

    # Save seen URLs so these articles are skipped next run
    new_urls = [s["url"] for s in stories if s.get("url")]
    seen.save(output_dir, new_urls)
    print(f"[seen] Saved {len(new_urls)} article URLs to history.")

    if args.dry_run:
        print("[dry-run] Skipping TTS synthesis.")
        return

    # 5. Synthesize
    print("=== Synthesizing audio ===")
    voice = cfg.get("tts", {}).get("voice", "am_michael")
    wav_path = tts.synthesize(script, output_dir=output_dir, voice=voice)

    print(f"\nDone. Output: {wav_path}")

    if not args.no_play:
        print("=== Playing audio ===")
        subprocess.run(["afplay", str(wav_path)])


if __name__ == "__main__":
    main()
