"""Shared helpers for all scrapers.

Every scraper returns a list of dicts with these consistent fields:
    source, title, text, url, timestamp
Use `make_record` to build them so the shape never drifts between scrapers.
"""

import time
from datetime import datetime, timezone

import requests

# A descriptive User-Agent is required by Reddit (and polite everywhere else).
USER_AGENT = "market-consensus/0.1 (daily market sentiment aggregator)"

# Be a good citizen: this pipeline runs once a day, so a short pause between
# requests is plenty to stay well under any rate limit.
REQUEST_DELAY_SECONDS = 2

HEADERS = {"User-Agent": USER_AGENT}


def polite_get(url, params=None, timeout=15, headers=None):
    """GET a URL with the standard headers, then sleep to respect rate limits.

    The sleep happens *after* the request so callers can loop over URLs without
    having to remember to pause themselves. Pass `headers` to override the
    defaults (e.g. a site-specific User-Agent).
    """
    merged = {**HEADERS, **(headers or {})}
    response = requests.get(url, headers=merged, params=params, timeout=timeout)
    response.raise_for_status()
    time.sleep(REQUEST_DELAY_SECONDS)
    return response


def make_record(source, title, text, url, timestamp):
    """Build a single normalized record with the canonical field shape."""
    return {
        "source": source,
        "title": title,
        "text": text,
        "url": url,
        "timestamp": timestamp,
    }


def to_iso(dt):
    """Normalize a datetime (or unix epoch seconds) to an ISO-8601 UTC string."""
    if dt is None:
        return None
    if isinstance(dt, (int, float)):
        dt = datetime.fromtimestamp(dt, tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()
