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


class StanceScoringError(RuntimeError):
    """Scoring failed for reasons that are NOT 'the posts were irrelevant'.

    Exists because those two outcomes used to be indistinguishable. Every exception
    was swallowed into `None`, which the caller reads as "not relevant" — so an
    expired key or an exhausted credit balance produced an empty result set, and the
    UI reported "No discussion found for Nvidia" instead of an error. A billing
    problem looked exactly like a coverage gap, on the site and in the seed script's
    own coverage report. Raising is the honest outcome: callers can catch it, but
    nobody can mistake it for data.
    """


def _is_fatal(exc: Exception) -> bool:
    """True for errors that will never succeed on retry — config/auth/billing.

    Deliberately NOT including 429: a rate limit is genuinely transient and the
    backoff below is the right response to it. This is only for the class of
    failure where every subsequent call is guaranteed to fail the same way.
    """
    import anthropic

    return isinstance(exc, (
        anthropic.AuthenticationError,    # 401 — bad/absent key
        anthropic.PermissionDeniedError,  # 403
        anthropic.BadRequestError,        # 400 — includes "credit balance is too low"
        anthropic.NotFoundError,          # 404 — e.g. wrong model id
    ))


def _score_one(client, rec: dict, subject_name: str, max_retries: int = 4):
    """Score one item. Returns the enriched rec if relevant, None if not.

    Raises on fatal (auth/billing/config) errors rather than reporting them as
    irrelevance. Transient errors still retry with exponential backoff and, if they
    never clear, raise too — `score_stance` decides whether a given failure rate is
    tolerable, because only it can see the whole batch.
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
        except (json.JSONDecodeError, KeyError, ValueError, IndexError):
            # The model returned something unparseable. That's about this one item,
            # not the run — drop it and move on, as before.
            return None
        except Exception as e:  # noqa: BLE001
            if _is_fatal(e):
                raise
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue
            raise  # transient, but it never cleared — let score_stance judge
    return None


# If more than this share of a batch errors out, the result isn't a measurement —
# something is wrong with the key, the account, or the network, and an empty/thin
# result would misrepresent it as "nobody is talking about this subject".
MAX_ERROR_RATE = 0.25


def score_stance(records: list[dict], subject_name: str, max_workers: int = 8,
                 quiet: bool = False) -> list[dict]:
    """Score records' stance with Claude Haiku, CONCURRENTLY. Returns relevant ones.

    Uses a thread pool because scoring is I/O-bound (network round-trips): 8 in
    flight turns a ~45-min sequential batch into a few minutes. One shared client
    is thread-safe. Order doesn't matter — we bucket by timestamp downstream.

    Raises StanceScoringError if a fatal error occurs or too much of the batch fails
    (see MAX_ERROR_RATE). A few scattered failures are tolerated and logged — the
    point is to never let a broken pipeline masquerade as a quiet corpus.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from anthropic import Anthropic

    client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    scored: list[dict] = []
    n = len(records)
    done = 0
    errors: list[Exception] = []
    fatal: Exception | None = None

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_score_one, client, rec, subject_name) for rec in records]
        for fut in as_completed(futures):
            done += 1
            try:
                result = fut.result()
            except Exception as e:  # noqa: BLE001 — tallied and judged below
                errors.append(e)
                if fatal is None and _is_fatal(e):
                    fatal = e
            else:
                if result is not None:
                    scored.append(result)
            if not quiet and (done % 25 == 0 or done == n):
                note = f", {len(errors)} errors" if errors else ""
                print(f"  scored {done}/{n} … kept {len(scored)} relevant{note}")

    if fatal is not None:
        raise StanceScoringError(
            f"stance scoring aborted for '{subject_name}': {type(fatal).__name__}: {fatal}"
        ) from fatal
    if n and len(errors) / n > MAX_ERROR_RATE:
        raise StanceScoringError(
            f"stance scoring failed for '{subject_name}': {len(errors)}/{n} items errored "
            f"(> {MAX_ERROR_RATE:.0%}). Refusing to report this as a low-coverage result — "
            f"last error: {type(errors[-1]).__name__}: {errors[-1]}"
        ) from errors[-1]
    if errors and not quiet:
        print(f"  note: {len(errors)}/{n} items failed scoring and were dropped")

    return scored
