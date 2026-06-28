"""Reddit scraper.

Reddit blocks the unauthenticated JSON API (`/hot.json`) at the IP level for
most clients now, so this uses the public RSS feed (`/hot/.rss`) instead, which
still serves read-only data without auth. We fetch the bytes ourselves (with a
browser-style User-Agent + our rate-limit pause) and hand them to feedparser,
because feedparser's own fetch gets rate-limited (429) more aggressively.

The RSS feed is lighter than the JSON API (no score/selftext body), which is
fine for Phase 1. When we want richer signal (score, comment counts) we should
switch to the official OAuth API — see the note in README/.env.
"""

import time

import feedparser

from .utils import make_record, polite_get, to_iso

SUBREDDITS = ["investing", "stocks"]

# Reddit's RSS is friendlier to a browser-like UA than the descriptive default.
_REDDIT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def scrape_subreddit(subreddit, limit=25, retries=3):
    """Scrape hot posts from a single subreddit via its RSS feed.

    Retries with exponential backoff on transient rate-limiting (429), since a
    single IP can get throttled even for a once-daily request.
    """
    url = f"https://www.reddit.com/r/{subreddit}/hot/.rss"
    params = {"limit": limit}

    last_exc = None
    for attempt in range(retries):
        try:
            response = polite_get(url, params=params, headers={"User-Agent": _REDDIT_UA})
            return _parse_feed(response.content, subreddit, limit)
        except Exception as exc:  # noqa: BLE001 - retry any transient failure
            last_exc = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429 and attempt < retries - 1:
                backoff = 5 * (attempt + 1)
                print(f"    r/{subreddit}: 429, backing off {backoff}s...")
                time.sleep(backoff)
                continue
            raise

    raise last_exc


def _parse_feed(content, subreddit, limit):
    """Parse RSS bytes into normalized records."""
    feed = feedparser.parse(content)

    records = []
    for entry in feed.entries[:limit]:
        title = entry.get("title", "")
        # RSS gives an HTML summary; fall back to the title if it's empty.
        text = entry.get("summary", "") or title

        timestamp = None
        if entry.get("published_parsed"):
            import calendar

            timestamp = to_iso(calendar.timegm(entry["published_parsed"]))

        records.append(
            make_record(
                source=f"reddit/r/{subreddit}",
                title=title,
                text=text,
                url=entry.get("link", ""),
                timestamp=timestamp,
            )
        )

    return records


def scrape(limit=25):
    """Scrape all configured subreddits and return a combined list of records."""
    records = []
    for subreddit in SUBREDDITS:
        records.extend(scrape_subreddit(subreddit, limit=limit))
    return records
