"""Subject resolver — any market string → search terms + a tradeable proxy.

This replaces the hardcoded `SUBJECTS` dict in `slice1_prove_loop.py`. A user types
anything tradeable ("uranium miners", "Nvidia", "the AI trade", "Bitcoin",
"small-cap biotech"); Claude Haiku resolves it into everything the engine needs:
how to search each source, and the ticker/ETF the backtest anchors to.

Scope is MARKETS (see docs/BUILD_PLAN.md): every subject should resolve to a
tradeable proxy. If a string genuinely has no market proxy, `is_financial` is
False and `proxy` is None — the caller can decline it rather than pretend.

Cheap + cached: one Haiku call per distinct subject, memoized in-process and
persisted to `.subject_cache.json` so repeat resolves are free and deterministic.

Requires ANTHROPIC_API_KEY (loaded by scrapers.utils on import).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

# Ensure .env is loaded.
from scrapers import utils  # noqa: F401

MODEL = "claude-haiku-4-5"
_CACHE_PATH = Path(".subject_cache.json")


class ResolvedSubject(BaseModel):
    """Everything the engine needs to find + price a market subject."""

    display: str = Field(description="Clean human-readable name, e.g. 'Nvidia' or 'Uranium miners'.")
    asset_type: str = Field(description="One of: stock, sector, crypto, commodity, index, other.")
    is_financial: bool = Field(description="True if this is a tradeable market subject with a real proxy.")
    proxy: str | None = Field(description="The single best tradeable ticker/ETF for the backtest, or null if none.")
    hn_query: str = Field(description="Best Hacker News search phrase (companies discussed by NAME, not ticker).")
    reddit_query: str = Field(description="Reddit search query; may use OR, e.g. 'NVDA OR Nvidia'.")
    subreddits: list[str] = Field(description="2-4 relevant subreddits (no 'r/' prefix), most relevant first.")
    aliases: list[str] = Field(description="Other names/tickers people use for this subject.")


_SYSTEM = """You resolve a user's free-text MARKET subject into structured search + pricing metadata.

The product analyzes crowd sentiment about tradeable things: individual stocks, \
sectors/themes, crypto, commodities, indices. Given ANY subject string, return the \
fields that let a pipeline (a) find where it's discussed and (b) anchor it to a price.

Rules:
- proxy: pick the SINGLE most representative liquid ticker or ETF. A company → its \
ticker (Nvidia→NVDA). A sector/theme → the canonical ETF (semiconductors→SOXX, \
uranium miners→URA, clean energy→ICLN, the AI trade→ a leading proxy like NVDA or \
an AI ETF). Crypto → the yfinance pair (Bitcoin→BTC-USD, Ethereum→ETH-USD). If there \
is genuinely no tradeable proxy, set is_financial=false and proxy=null.
- hn_query: Hacker News discusses companies by NAME, not ticker. Use the name/topic.
- subreddits: choose real, active investing/crypto subreddits relevant to THIS subject \
(e.g. wallstreetbets, stocks, investing for equities; CryptoCurrency, Bitcoin for coins; \
a ticker/topic sub when one clearly exists). No 'r/' prefix.
- Be precise, not verbose. Judge the subject as a market instrument."""


def _load_disk_cache() -> dict:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text())
        except Exception:  # noqa: BLE001 — a corrupt cache shouldn't break resolving
            return {}
    return {}


_MEM_CACHE: dict = _load_disk_cache()


def _save_disk_cache() -> None:
    try:
        _CACHE_PATH.write_text(json.dumps(_MEM_CACHE, indent=2))
    except Exception:  # noqa: BLE001 — caching is best-effort
        pass


def resolve(subject: str, use_cache: bool = True) -> dict:
    """Resolve a free-text market subject into a dict (see ResolvedSubject).

    Cached by the normalized subject string. Adds `input` (the raw query) to the
    returned dict so callers can echo what the user actually typed.
    """
    key = subject.strip().lower()
    if use_cache and key in _MEM_CACHE:
        return _MEM_CACHE[key]

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set — cannot resolve subjects")

    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.parse(
        model=MODEL,
        max_tokens=400,
        system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"Subject: {subject.strip()}"}],
        output_format=ResolvedSubject,
    )
    resolved = resp.parsed_output.model_dump()
    resolved["input"] = subject.strip()
    # Normalize the proxy to uppercase (yfinance is case-insensitive but this is tidy).
    if resolved.get("proxy"):
        resolved["proxy"] = resolved["proxy"].upper()

    _MEM_CACHE[key] = resolved
    _save_disk_cache()
    return resolved


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) or "uranium miners"
    r = resolve(query)
    print(json.dumps(r, indent=2))
