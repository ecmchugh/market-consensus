"""Persistence — save each day's consensus to Supabase (Postgres).

One row per day in `daily_consensus`, keyed by run_date. Re-running the same
day upserts (overwrites) rather than creating duplicates, so a day always
reflects the latest run.

Writes use the SUPABASE_KEY (service/secret key), which bypasses row-level
security — so this is a trusted backend writer. Requires SUPABASE_URL and
SUPABASE_KEY in .env (loaded by scrapers.utils on import).
"""

import os
from datetime import datetime, timezone

from supabase import create_client

# Ensure .env is loaded (utils calls load_dotenv() on import).
from scrapers import utils  # noqa: F401

TABLE = "daily_consensus"


def is_configured():
    """True if Supabase credentials are present."""
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"))


def _client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not (url and key):
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY not set in .env")
    return create_client(url, key)


def _row(result, run_date):
    """Map an aggregate() result to a daily_consensus row."""
    return {
        "run_date": run_date,
        "consensus_score": result["consensus_score"],
        "label": result["label"],
        "confidence": result["confidence"],
        "contested": result["contested"],
        "dispersion": result["dispersion"],
        "item_count": result["item_count"],
        "contributing_count": result["contributing_count"],
        # JSONB columns — dicts/lists stored natively. int tier keys serialize
        # to strings in JSON, which is expected.
        "tier_means": result["tier_means"],
        "tickers": result["tickers"],
        "top_themes": result["top_themes"],
        "bull_signals": result["bull_signals"],
        "bear_signals": result["bear_signals"],
    }


def save(result, run_date=None):
    """Upsert one day's consensus. Returns the run_date used."""
    run_date = run_date or datetime.now(timezone.utc).date().isoformat()
    client = _client()
    client.table(TABLE).upsert(_row(result, run_date), on_conflict="run_date").execute()
    return run_date


def latest(limit=30):
    """Fetch the most recent daily rows (newest first) for trends/backtest."""
    client = _client()
    resp = (
        client.table(TABLE)
        .select("*")
        .order("run_date", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data
