"""Normalize raw scraper output into one consistent schema.

Each scraper emits its own natural shape; this module is the single place that
produces the canonical record the rest of the pipeline depends on:

    {
        "source":         "reddit/r/investing",   # kept detailed for debugging
        "source_tier":    3,                       # 1=arxiv, 2=news, 3=reddit
        "title":          "...",
        "text":           "...",                   # truncated to 500 chars
        "url":            "...",
        "timestamp":      "2026-06-28T10:00:00+00:00",
        "raw_engagement": 4500,                    # upvotes; 0 for non-social
    }

Assigning the tier here (not in the scrapers) keeps source-weighting policy in
one place. The tier table itself lives in config.py.
"""

from config import DEFAULT_TIER, SOURCE_TIERS

TEXT_MAX_CHARS = 500


def tier_for_source(source):
    """Map a raw `source` string to its tier (lower = more authoritative)."""
    for prefix, tier in SOURCE_TIERS:
        if source.startswith(prefix):
            return tier
    return DEFAULT_TIER


def _engagement(raw):
    """Flatten the scraper's metadata dict to a single integer.

    Reddit posts carry a `score` (upvotes); other sources have none → 0.
    """
    score = (raw.get("metadata") or {}).get("score")
    return int(score) if isinstance(score, (int, float)) else 0


def normalize_record(raw):
    """Convert one raw scraper record into the canonical schema."""
    source = raw.get("source", "")
    text = (raw.get("text") or "").strip()
    return {
        "source": source,
        "source_tier": tier_for_source(source),
        "title": (raw.get("title") or "").strip(),
        "text": text[:TEXT_MAX_CHARS],
        "url": raw.get("url", ""),
        "timestamp": raw.get("timestamp"),
        "raw_engagement": _engagement(raw),
    }


def normalize(records):
    """Normalize a list of raw records into canonical records."""
    return [normalize_record(r) for r in records]
