"""Reddit scraper (official OAuth API).

Uses Reddit's OAuth API via the *userless* "client_credentials" flow, which
only needs a client ID + secret (no Reddit password). This is reliable from
datacenter IPs (e.g. Railway) where the unauthenticated endpoints get 403'd,
and it returns rich engagement data (score, comments, upvote ratio) that's
useful for weighting sentiment later.

Setup: create a "script" app at https://www.reddit.com/prefs/apps and put the
credentials in .env:
    REDDIT_CLIENT_ID=...
    REDDIT_CLIENT_SECRET=...

If credentials are absent, we fall back to the public RSS feed so the pipeline
still produces (lighter) data — see `_scrape_subreddit_rss`.
"""

import os

import feedparser
import requests

from .utils import USER_AGENT, make_record, polite_get, to_iso

SUBREDDITS = ["investing", "stocks"]

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_API_BASE = "https://oauth.reddit.com"


def _get_token():
    """Fetch a userless OAuth access token, or return None if no credentials."""
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    response = requests.post(
        _TOKEN_URL,
        auth=requests.auth.HTTPBasicAuth(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _scrape_subreddit_oauth(subreddit, token, limit):
    """Scrape hot posts from one subreddit via the authenticated API."""
    response = polite_get(
        f"{_API_BASE}/r/{subreddit}/hot",
        params={"limit": limit},
        headers={"Authorization": f"bearer {token}", "User-Agent": USER_AGENT},
    )
    payload = response.json()

    records = []
    for child in payload.get("data", {}).get("children", []):
        post = child.get("data", {})
        if post.get("stickied"):  # mod pins aren't market signal
            continue

        title = post.get("title", "")
        text = post.get("selftext", "") or title
        records.append(
            make_record(
                source=f"reddit/r/{subreddit}",
                title=title,
                text=text,
                url=f"https://www.reddit.com{post.get('permalink', '')}",
                timestamp=to_iso(post.get("created_utc")),
                metadata={
                    "score": post.get("score"),
                    "num_comments": post.get("num_comments"),
                    "upvote_ratio": post.get("upvote_ratio"),
                },
            )
        )
    return records


def _scrape_subreddit_rss(subreddit, limit):
    """Fallback: scrape via the public RSS feed (no engagement metadata)."""
    browser_ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
    response = polite_get(
        f"https://www.reddit.com/r/{subreddit}/hot/.rss",
        params={"limit": limit},
        headers={"User-Agent": browser_ua},
    )
    feed = feedparser.parse(response.content)

    records = []
    for entry in feed.entries[:limit]:
        title = entry.get("title", "")
        timestamp = None
        if entry.get("published_parsed"):
            import calendar

            timestamp = to_iso(calendar.timegm(entry["published_parsed"]))
        records.append(
            make_record(
                source=f"reddit/r/{subreddit}",
                title=title,
                text=entry.get("summary", "") or title,
                url=entry.get("link", ""),
                timestamp=timestamp,
            )
        )
    return records


def scrape(limit=25):
    """Scrape all configured subreddits and return a combined list of records.

    Uses OAuth when credentials are present, otherwise the RSS fallback.
    """
    token = _get_token()
    if token is None:
        print("  (reddit: no OAuth credentials, using RSS fallback)")

    records = []
    for subreddit in SUBREDDITS:
        if token:
            records.extend(_scrape_subreddit_oauth(subreddit, token, limit))
        else:
            records.extend(_scrape_subreddit_rss(subreddit, limit))
    return records
