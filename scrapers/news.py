"""News scrapers — financial press RSS feeds (the 'professional' voice).

Pulls several outlets so the press view is a representative chorus, not one
source. Every outlet is labeled `news:<outlet>` so it maps to the news tier
(config.SOURCE_TIERS matches the `news` prefix). One flaky feed never kills the
rest.

Feeds are fetched with a browser-style User-Agent (some outlets block generic
agents) and rate-limited via polite_get.
"""

import calendar

import feedparser

from .utils import make_record, polite_get, to_iso

# Some outlets (e.g. Seeking Alpha) reject non-browser agents.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# (source label, feed URL). Stocks/markets focus. Reuters dropped public RSS,
# so Nasdaq stands in. Add outlets here — no other code changes needed.
FEEDS = [
    ("news:yahoo-finance",
     "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US"),
    ("news:marketwatch",
     "http://feeds.marketwatch.com/marketwatch/marketpulse/"),
    ("news:cnbc",
     "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069"),
    ("news:seeking-alpha",
     "https://seekingalpha.com/feed.xml"),
    ("news:investing",
     "https://www.investing.com/rss/news_25.rss"),
    ("news:nasdaq",
     "https://www.nasdaq.com/feed/rssoutbound?category=Stocks"),
]


def _scrape_feed(source, url, limit):
    """Fetch and parse one RSS feed into normalized records."""
    response = polite_get(url, headers={"User-Agent": _UA})
    feed = feedparser.parse(response.content)

    records = []
    for entry in feed.entries[:limit]:
        title = entry.get("title", "")
        text = entry.get("summary", "") or title  # short summaries; fall back to title

        timestamp = None
        if entry.get("published_parsed"):
            timestamp = to_iso(calendar.timegm(entry["published_parsed"]))

        records.append(
            make_record(
                source=source,
                title=title,
                text=text,
                url=entry.get("link", ""),
                timestamp=timestamp,
            )
        )
    return records


def scrape(limit=25):
    """Fetch every configured news feed; a failing outlet is skipped, not fatal."""
    records = []
    for source, url in FEEDS:
        try:
            records.extend(_scrape_feed(source, url, limit))
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {source} failed: {exc}")
    return records
