"""Abuse and spend guards for the public API.

`POST /subjects/query` is the only endpoint that costs money: a cold run fires one
Haiku call per fetched post plus a Sonnet synthesis, and takes ~40s. Exposed on the
open internet with no guard, a single loop could drain the Anthropic key — no
exploit required. Two independent limits sit in front of it:

  1. **Per-IP rate limit** (sliding window). Applied BEFORE any LLM work, including
     subject resolution, so spraying novel subjects can't run up Haiku resolver
     calls. Bounds what one client can do.

  2. **Global daily cold-run budget.** Bounds total spend regardless of how many
     clients show up. Derived from the store rather than a counter in memory: every
     cold run writes exactly one `subject_reading` row, so "rows written since
     midnight UTC" IS the number of cold runs today. That survives process restarts,
     which an in-memory counter would not.

Both are configured by env var and can be disabled by setting them to 0.

KNOWN LIMITS (documented rather than hidden):
  * The rate limiter is per-process. Behind >1 worker/replica the effective limit is
    multiplied by the worker count. Fine for the single-instance deploy this targets;
    a shared Redis counter is the fix if it ever scales out.
  * The budget counts *successful* cold runs. A run that spends tokens and then
    fails writes no row, so it isn't charged against the budget.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request


def _int_env(name: str, default: int) -> int:
    """Non-negative int from the environment; 0 disables the guard."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


# Queries one IP may make in the window. Generous for a human (a real session is a
# handful of subjects), tight enough that a scraper hits it immediately.
QUERY_RATE_LIMIT = _int_env("QUERY_RATE_LIMIT", 20)
QUERY_RATE_WINDOW_S = _int_env("QUERY_RATE_WINDOW_S", 3600)

# Hard ceiling on cold runs per UTC day, across all clients. This is the actual
# spend cap: cold runs are the only thing that costs meaningful money.
DAILY_COLD_QUERY_BUDGET = _int_env("DAILY_COLD_QUERY_BUDGET", 100)


class SlidingWindowLimiter:
    """In-process sliding-window counter keyed by client.

    Chosen over a fixed window so a client can't burst 2x the limit across a window
    boundary. Memory is bounded by pruning empty keys on a timer.
    """

    def __init__(self, limit: int, window_s: int):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def check(self, key: str) -> float | None:
        """Record a hit. Returns None if allowed, else seconds until retry."""
        if self.limit <= 0 or self.window_s <= 0:
            return None  # disabled

        now = time.monotonic()
        cutoff = now - self.window_s
        with self._lock:
            self._sweep(now, cutoff)
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1.0, hits[0] + self.window_s - now)
            hits.append(now)
            return None

    def _sweep(self, now: float, cutoff: float) -> None:
        """Drop keys with no recent hits so idle clients don't accumulate."""
        if now - self._last_sweep < self.window_s:
            return
        self._last_sweep = now
        for k in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
            del self._hits[k]


_query_limiter = SlidingWindowLimiter(QUERY_RATE_LIMIT, QUERY_RATE_WINDOW_S)


def client_key(request: Request) -> str:
    """Best-effort client identity for rate limiting.

    Railway/Vercel terminate TLS upstream, so the socket peer is the proxy — the
    real client is the first entry of X-Forwarded-For. That header is spoofable by
    anyone talking to the origin directly, so this is a speed bump against casual
    abuse, not an authentication mechanism. The daily budget is the guard that
    holds regardless of what a client claims about itself.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request) -> None:
    """429 if this client has exceeded its window. Call before any paid work."""
    retry_after = _query_limiter.check(client_key(request))
    if retry_after is None:
        return
    raise HTTPException(
        status_code=429,
        detail=(
            f"Rate limit reached ({QUERY_RATE_LIMIT} queries per "
            f"{QUERY_RATE_WINDOW_S // 60} minutes). Try again shortly — "
            "subjects already read are served from cache without limit."
        ),
        headers={"Retry-After": str(int(retry_after))},
    )


def utc_day_start() -> str:
    """ISO timestamp for 00:00 UTC today — the budget window boundary."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def enforce_daily_budget(store) -> None:
    """503 if today's cold-run budget is spent.

    A store that doesn't implement the count (older backend) fails OPEN with the
    rate limiter still in front — noted so a silent loss of the cap is visible in
    logs rather than mistaken for "the cap is working".
    """
    if DAILY_COLD_QUERY_BUDGET <= 0:
        return  # disabled
    try:
        used = store.count_readings_since(utc_day_start())
    except (AttributeError, NotImplementedError):
        print("WARNING: store cannot count readings — daily spend cap is NOT enforced")
        return
    if used < DAILY_COLD_QUERY_BUDGET:
        return

    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    raise HTTPException(
        status_code=503,
        detail=(
            f"Daily query budget reached ({DAILY_COLD_QUERY_BUDGET} new readings). "
            "Subjects already in the corpus still work — they're served from cache. "
            "New readings resume at 00:00 UTC."
        ),
        headers={"Retry-After": str(int((tomorrow - datetime.now(timezone.utc)).total_seconds()))},
    )
