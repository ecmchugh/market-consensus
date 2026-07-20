"""Stance scoring — per-item directional conviction via Claude Haiku, concurrently.

Graduated verbatim from `slice1_prove_loop.py` (STAGE 2+3). This is the
Haiku-for-volume half of the cost split; Sonnet-once-per-query synthesis lives in
the query path. Distinct from the legacy `pipeline/scorer.py` (Opus + Batch API,
used by the old news pipeline) — this is the engine the consensus product uses.

Key properties:
  * FIXED rubric in the system prompt → identical for every item (reproducible)
    and prompt-cached across the batch (cost).
  * CONCURRENT: I/O-bound network calls run across a thread pool, turning a
    ~45-min sequential batch into a few minutes.
  * Each item is judged for `relevant` first; irrelevant items are dropped so
    downstream aggregation only sees genuine views about the subject.

Requires ANTHROPIC_API_KEY in .env (loaded by scrapers.utils on import).
"""

from __future__ import annotations

import json
import time

# Ensure .env (ANTHROPIC_API_KEY) is loaded — utils calls load_dotenv() on import.
from scrapers import utils  # noqa: F401

MODEL = "claude-haiku-4-5"  # cheap + fast for high-volume per-item scoring (cost discipline)

# The rubric lives in the system prompt so it's identical for every item
# (reproducibility) and gets prompt-cached across the batch (cost).
STANCE_SYSTEM = """You score how a single social-media post feels about a specific stock/subject.

You are measuring SENTIMENT (mood/conviction), not making a price prediction.

Return STRICT JSON, no prose, with exactly these keys:
  "relevant": boolean — true only if the post actually expresses a view about the subject
              (skip pure news links, giveaways, off-topic mentions).
  "score": integer from -100 to 100 — the poster's directional conviction about the subject:
              +100 = maximally bullish/excited, 0 = neutral/mixed, -100 = maximally bearish/fearful.
  "rationale": string — at most 12 words, why.

Judge the poster's own stance. Account for sarcasm, irony, and crypto/WSB slang
("puts", "calls", "bag", "ngmi", "to the moon", "drilling", "printing"). If the
post is not genuinely about the subject, set relevant=false and score=0."""


def _score_one(client, rec: dict, subject_name: str, max_retries: int = 4):
    """Score one item. Returns the enriched rec if relevant, else None.

    Retries with exponential backoff on transient/rate-limit errors so a big
    concurrent batch degrades gracefully instead of dropping items.
    """
    content = f"SUBJECT: {subject_name}\n\nPOST TITLE: {rec['title']}\n\nPOST BODY: {rec['text'][:1500]}"
    for attempt in range(max_retries):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=120,
                system=[{"type": "text", "text": STANCE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[
                    {"role": "user", "content": content},
                    {"role": "assistant", "content": "{"},  # prefill → forces clean JSON
                ],
            )
            data = json.loads("{" + resp.content[0].text)
            if not data.get("relevant"):
                return None
            return {**rec, "score": int(data["score"]), "rationale": data.get("rationale", "")}
        except Exception:  # noqa: BLE001 — retry transient errors, give up after max_retries
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue
            return None
    return None


def score_stance(records: list[dict], subject_name: str, max_workers: int = 8,
                 quiet: bool = False) -> list[dict]:
    """Score records' stance with Claude Haiku, CONCURRENTLY. Returns relevant ones.

    Uses a thread pool because scoring is I/O-bound (network round-trips): 8 in
    flight turns a ~45-min sequential batch into a few minutes. One shared client
    is thread-safe. Order doesn't matter — we bucket by timestamp downstream.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from anthropic import Anthropic

    client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    scored: list[dict] = []
    n = len(records)
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_score_one, client, rec, subject_name) for rec in records]
        for fut in as_completed(futures):
            done += 1
            result = fut.result()
            if result is not None:
                scored.append(result)
            if not quiet and (done % 25 == 0 or done == n):
                print(f"  scored {done}/{n} … kept {len(scored)} relevant")

    return scored
