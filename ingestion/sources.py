"""Source fetchers — Hacker News (informed) and Reddit (crowd).

Graduated verbatim from `slice1_prove_loop.py` so the same fetch code is
importable + testable by the query path and the backtest alike. Behavior is
unchanged; this is the reusable home for STAGE 1 (FETCH).

  * Hacker News (`fetch_hn`) — zero-auth Algolia search, windowed by month/week
    so every period gets coverage. Tagged source_type="informed".
  * Reddit (`fetch_reddit_posts`) — public per-subreddit search RSS (no OAuth),
    top-of-year. Tagged source_type="crowd".
"""

from __future__ import annotations

import html
import re

import feedparser

# Reuse the scrapers' shared helpers (loads .env on import, polite rate-limited GET).
from scrapers.utils import USER_AGENT, polite_get, to_iso

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def strip_html(s: str) -> str:
    """Strip tags + unescape entities — enough to hand clean text to the model.

    Handles HN's hex entities (&#x27; etc.) and named entities via html.unescape.
    """
    text = re.sub(r"<[^>]+>", " ", s or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Reddit (crowd)
# ---------------------------------------------------------------------------
def fetch_reddit_posts(subject: dict, per_sub: int = 100) -> list[dict]:
    """Fetch subject-specific posts via Reddit's public search RSS (no OAuth).

    We search each subreddit for the subject, sorted by top over the past year,
    so we get real posts with real timestamps spread across time.
    """
    records: list[dict] = []
    seen_urls: set[str] = set()

    for sub in subject["subreddits"]:
        url = f"https://www.reddit.com/r/{sub}/search.rss"
        params = {
            "q": subject["reddit_query"],
            "restrict_sr": "1",   # search within this subreddit only
            "sort": "top",
            "t": "year",
            "limit": str(per_sub),
        }
        try:
            resp = polite_get(url, params=params, headers={"User-Agent": BROWSER_UA})
        except Exception as e:  # noqa: BLE001 — one bad sub shouldn't kill the run
            print(f"  ! r/{sub}: fetch failed ({e.__class__.__name__}), skipping")
            continue

        feed = feedparser.parse(resp.content)
        n_before = len(records)
        for entry in feed.entries:
            link = entry.get("link", "")
            if link in seen_urls:
                continue
            seen_urls.add(link)

            ts = None
            if entry.get("published_parsed"):
                import calendar
                ts = to_iso(calendar.timegm(entry["published_parsed"]))

            title = entry.get("title", "")
            # feedparser gives an HTML summary; strip tags crudely for the model.
            summary = entry.get("summary", "") or ""
            records.append(
                {
                    "source": f"reddit/r/{sub}",
                    "source_type": "crowd",
                    "title": title,
                    "text": strip_html(summary) or title,
                    "url": link,
                    "timestamp": ts,
                    "metadata": {},
                }
            )
        print(f"  r/{sub}: +{len(records) - n_before} posts")

    return records


# ---------------------------------------------------------------------------
# Hacker News (informed)
# ---------------------------------------------------------------------------
def _iter_windows(period: str, n: int):
    """Yield (start_unix, end_unix, label) for the last n periods, newest first.

    label is the bucket key downstream aggregation/price join on:
      month → "YYYY-MM";  week → the week's Monday date "YYYY-MM-DD".
    """
    import calendar
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    if period == "month":
        year, month = now.year, now.month
        for _ in range(n):
            start = datetime(year, month, 1, tzinfo=timezone.utc)
            last = calendar.monthrange(year, month)[1]
            end = datetime(year, month, last, 23, 59, 59, tzinfo=timezone.utc)
            yield int(start.timestamp()), int(end.timestamp()), f"{year}-{month:02d}"
            month -= 1
            if month == 0:
                month, year = 12, year - 1
    elif period == "week":
        monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(n):
            end = monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
            yield int(monday.timestamp()), int(end.timestamp()), monday.strftime("%Y-%m-%d")
            monday -= timedelta(days=7)
    else:
        raise ValueError(f"unknown period: {period}")


def fetch_hn(subject: dict, period: str = "month", windows: int = 12,
             per_window: int = 40) -> list[dict]:
    """Fetch subject-specific HN stories + comments via the Algolia search API.

    No credentials. We query one window (month or week) at a time so every period
    gets coverage (a single relevance search would cluster around a few big threads).
    Each item is tagged source_type="informed" — HN is the practitioner slice.
    """
    import requests

    query = subject["hn_query"]
    records: list[dict] = []
    seen: set[str] = set()

    for start_i, end_i, label in _iter_windows(period, windows):
        try:
            resp = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "query": query,
                    "tags": "(story,comment)",
                    "numericFilters": f"created_at_i>={start_i},created_at_i<={end_i}",
                    "hitsPerPage": str(per_window),
                },
                headers={"User-Agent": USER_AGENT},
                timeout=20,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except Exception as e:  # noqa: BLE001
            print(f"  ! HN {label}: fetch failed ({e.__class__.__name__}), skipping")
            hits = []

        n_before = len(records)
        for hit in hits:
            oid = hit.get("objectID")
            if not oid or oid in seen:
                continue
            seen.add(oid)

            if hit.get("comment_text"):
                title = hit.get("story_title") or "(comment)"
                text = strip_html(hit["comment_text"])
            else:
                title = hit.get("title") or ""
                text = strip_html(hit.get("story_text") or "") or title
            if not text:
                continue

            records.append(
                {
                    "source": "hackernews",
                    "source_type": "informed",
                    "title": title,
                    "text": text,
                    "url": f"https://news.ycombinator.com/item?id={oid}",
                    "timestamp": hit.get("created_at"),  # already ISO-8601
                    "metadata": {"points": hit.get("points"), "author": hit.get("author")},
                }
            )
        print(f"  HN {label}: +{len(records) - n_before}")

    return records


def fetch_hn_posts(subject: dict, months_back: int = 12, per_month: int = 40) -> list[dict]:
    """Backward-compatible monthly wrapper (used by the Slice-1 demo)."""
    return fetch_hn(subject, period="month", windows=months_back, per_window=per_month)
