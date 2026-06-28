"""Sentiment scoring via the Claude API.

Each normalized record is sent to Claude, which returns structured sentiment:
    sentiment_score  (-1.0 bearish .. +1.0 bullish)
    themes           (key topics)
    bull_signals / bear_signals

Design notes:
- **Structured outputs** (Pydantic schema) guarantee valid, parseable JSON —
  no "please respond with only JSON" prompt-wrangling.
- **Two paths, one interface:** `score(records, use_batch=False)`.
    * sync  — one request per item; fast feedback loop for development.
    * batch — the Batch API; ~50% cheaper and async, for the daily cron run.
- **Prompt caching** on the shared scoring instructions: the system prompt is
  identical across every item, so we pay for it once per run.

Requires ANTHROPIC_API_KEY in .env (loaded by scrapers.utils on import).
"""

import time

import anthropic
from pydantic import BaseModel

import config
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

# Ensure .env (ANTHROPIC_API_KEY) is loaded — utils calls load_dotenv() on import.
from scrapers import utils  # noqa: F401


class SentimentResult(BaseModel):
    """Structured sentiment for a single piece of content."""

    sentiment_score: float  # -1.0 (bearish) .. +1.0 (bullish)
    tickers: list[str]      # stock ticker symbols mentioned, uppercase
    themes: list[str]
    bull_signals: list[str]
    bear_signals: list[str]


SYSTEM_PROMPT = """You are a financial sentiment analyst. You read one piece of \
content (a news headline, a Reddit post, or a research abstract) and extract \
its market sentiment.

Return:
- sentiment_score: a number from -1.0 (strongly bearish) to +1.0 (strongly \
bullish). Use 0.0 for neutral, mixed, or non-directional content (e.g. most \
academic abstracts).
- tickers: stock ticker symbols explicitly mentioned, uppercase (e.g. NVDA, \
TSLA). Empty list if none. Do not invent tickers that aren't clearly present.
- themes: the key topics discussed (short phrases).
- bull_signals: concrete reasons the content implies upside, if any.
- bear_signals: concrete reasons the content implies downside, if any.

Judge only the sentiment expressed by the content itself. Be conservative: if \
the content is descriptive or non-directional, score it near 0.0."""

MAX_TOKENS = 1024

# Cache the (constant) system prompt across every scoring request in a run.
_SYSTEM = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]

# Structured-output schema derived from the Pydantic model. The Batch path needs
# the raw json_schema; deriving it here keeps a single source of truth with the
# sync path's parse(). The API requires additionalProperties: false.
_SCHEMA = {**SentimentResult.model_json_schema(), "additionalProperties": False}
_OUTPUT_CONFIG = {"format": {"type": "json_schema", "schema": _SCHEMA}}


def _user_content(record):
    """Build the per-item prompt from a normalized record."""
    return (
        f"SOURCE: {record['source']}\n"
        f"TITLE: {record['title']}\n"
        f"CONTENT: {record['text']}"
    )


def _clamp(score):
    """Keep the model's score within the contracted [-1.0, 1.0] range."""
    return max(-1.0, min(1.0, float(score)))


def _merge(record, result):
    """Return a copy of `record` enriched with sentiment fields."""
    return {
        **record,
        "sentiment_score": _clamp(result.sentiment_score),
        "tickers": result.tickers,
        "themes": result.themes,
        "bull_signals": result.bull_signals,
        "bear_signals": result.bear_signals,
    }


# --- Sync path -------------------------------------------------------------

def _score_one_sync(client, record):
    response = client.messages.parse(
        model=config.MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _user_content(record)}],
        output_format=SentimentResult,
    )
    return response.parsed_output


# --- Batch path ------------------------------------------------------------

def _score_batch(client, records, poll_seconds=30):
    """Score all records via the Batch API. Returns results aligned to input."""
    requests = [
        Request(
            custom_id=f"item-{i}",
            params=MessageCreateParamsNonStreaming(
                model=config.MODEL,
                max_tokens=MAX_TOKENS,
                system=_SYSTEM,
                messages=[{"role": "user", "content": _user_content(rec)}],
                output_config=_OUTPUT_CONFIG,
            ),
        )
        for i, rec in enumerate(records)
    ]

    batch = client.messages.batches.create(requests=requests)
    print(f"  batch {batch.id} submitted ({len(requests)} items)...")

    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        time.sleep(poll_seconds)

    # Results arrive in any order — key by custom_id, then realign to input.
    by_id = {}
    for result in client.messages.batches.results(batch.id):
        if result.result.type == "succeeded":
            text = next(
                (b.text for b in result.result.message.content if b.type == "text"),
                None,
            )
            by_id[result.custom_id] = SentimentResult.model_validate_json(text)
        else:
            print(f"  !! {result.custom_id} {result.result.type}")
            by_id[result.custom_id] = None

    return [by_id.get(f"item-{i}") for i in range(len(records))]


# --- Public interface ------------------------------------------------------

def score(records, use_batch=False):
    """Score normalized records, returning them enriched with sentiment fields.

    Records that fail to score are dropped (with a warning) so downstream
    aggregation only sees usable sentiment.
    """
    if not records:
        return []

    client = anthropic.Anthropic()
    if use_batch:
        results = _score_batch(client, records)
    else:
        results = [_score_one_sync(client, rec) for rec in records]

    scored = []
    for rec, res in zip(records, results):
        if res is None:
            print(f"  dropped (no score): {rec['source']} — {rec['title'][:50]}")
            continue
        scored.append(_merge(rec, res))
    return scored
