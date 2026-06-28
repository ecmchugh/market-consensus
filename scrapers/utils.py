"""Shared helpers for all scrapers.

Every scraper returns a list of dicts with these consistent fields:
    source, title, text, url, timestamp, metadata
`metadata` is a dict for source-specific extras (e.g. Reddit score/comments);
it's always present (defaulting to {}) so the shape never drifts.
Use `make_record` to build records so this stays consistent everywhere.
"""

import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

# Load .env once at import so every scraper can read credentials via os.getenv.
load_dotenv()

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


def make_record(source, title, text, url, timestamp, metadata=None):
    """Build a single normalized record with the canonical field shape.

    `metadata` holds source-specific extras (Reddit score/comments, etc.) and is
    always present as a dict so the record shape is identical across scrapers.
    """
    return {
        "source": source,
        "title": title,
        "text": text,
        "url": url,
        "timestamp": timestamp,
        "metadata": metadata or {},
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
