"""Reddit hot posts via PRAW (read-only)."""

import praw


def fetch(client_id: str, client_secret: str, user_agent: str,
          subreddits: list[str], max_posts: int = 5) -> list[dict]:
    """Return hot posts from configured subreddits."""
    if not client_id or not client_secret:
        print("[reddit] Skipping — client_id/client_secret not configured.")
        return []

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )

    stories = []
    for sub_name in subreddits:
        try:
            sub = reddit.subreddit(sub_name)
            for post in sub.hot(limit=max_posts):
                if post.is_self and not post.selftext:
                    continue
                stories.append({
                    "title": post.title,
                    "url": post.url,
                    "source": f"r/{sub_name}",
                    "blurb": post.selftext[:200].strip() if post.is_self else "",
                    "score": post.score,
                    "published": None,
                })
        except Exception as e:
            print(f"[reddit] Error fetching r/{sub_name}: {e}")

    return stories
