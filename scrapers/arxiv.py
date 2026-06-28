"""arXiv scraper for recent finance/economics papers.

Uses the arXiv API (export.arxiv.org/api/query) rather than the RSS feed: the
RSS feed only reflects daily *announcements* and is empty on weekends/holidays,
which would blank this source ~2 days a week. The API queries by category
sorted by submission date and returns results any day.

arXiv is a *themes-only* source for this project — its abstracts surface what
researchers are focused on (structural context), not daily directional market
sentiment. The aggregator weights it accordingly.
"""

import feedparser

from .utils import make_record, polite_get, to_iso

API_URL = "http://export.arxiv.org/api/query"

# q-fin.* = all quantitative finance subcategories; econ.GN = general economics.
SEARCH_QUERY = "cat:q-fin.* OR cat:econ.GN"


def scrape(limit=25):
    """Fetch the most recent finance/economics papers as normalized records."""
    response = polite_get(
        API_URL,
        params={
            "search_query": SEARCH_QUERY,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": limit,
        },
    )
    feed = feedparser.parse(response.content)

    records = []
    for entry in feed.entries[:limit]:
        # arXiv wraps titles/abstracts across lines; collapse whitespace.
        title = " ".join(entry.get("title", "").split())
        abstract = " ".join(entry.get("summary", "").split())

        timestamp = None
        if entry.get("published_parsed"):
            import calendar

            timestamp = to_iso(calendar.timegm(entry["published_parsed"]))

        records.append(
            make_record(
                source="arxiv",
                title=title,
                # The abstract is the substance for theme extraction.
                text=abstract or title,
                url=entry.get("link", ""),
                timestamp=timestamp,
            )
        )

    return records
