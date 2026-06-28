"""News scraper using Yahoo Finance's RSS feed via feedparser."""

import feedparser

from .utils import make_record, to_iso

# Yahoo Finance headlines RSS. The region/lang params keep results US-English.
YAHOO_FINANCE_RSS = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US"
)


def scrape(limit=25):
    """Fetch headlines from the Yahoo Finance RSS feed.

    feedparser handles the HTTP fetch and XML parsing itself, so there's no
    separate request to rate-limit here — this is a single call once a day.
    """
    feed = feedparser.parse(YAHOO_FINANCE_RSS, agent="market-consensus/0.1")

    records = []
    for entry in feed.entries[:limit]:
        title = entry.get("title", "")
        # RSS summaries are short; fall back to the title if there's no body.
        text = entry.get("summary", "") or title

        # feedparser exposes the parsed date as a time.struct_time.
        published = entry.get("published_parsed")
        timestamp = None
        if published:
            import calendar

            timestamp = to_iso(calendar.timegm(published))

        records.append(
            make_record(
                source="yahoo-finance",
                title=title,
                text=text,
                url=entry.get("link", ""),
                timestamp=timestamp,
            )
        )

    return records
