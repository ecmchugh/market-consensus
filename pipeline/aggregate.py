"""Aggregation — roll scored items into per-period conviction readings.

Graduated verbatim from `slice1_prove_loop.py` (STAGE 4). Distinct from the legacy
`pipeline/aggregator.py` (the old news pipeline's tier-weighted daily consensus) —
this is the period-bucketed roll-up the subject engine + backtest use.

Equal-weighted for now; `min_items` drops thin buckets (important weekly, where a
1-item week is just noise).
"""

from __future__ import annotations

from collections import defaultdict


def bucket_key(iso_ts: str, period: str) -> str:
    """Map an ISO timestamp to its bucket key: month 'YYYY-MM' or week's Monday date."""
    if period == "month":
        return iso_ts[:7]
    from datetime import date, timedelta
    d = date.fromisoformat(iso_ts[:10])
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat()


def aggregate_by_period(scored: list[dict], period: str = "month",
                        min_items: int = 1) -> list[dict]:
    """Roll scored items into a per-period conviction reading (key: 'period').

    Equal-weighted for now. `min_items` drops thin buckets — important weekly, where
    a 1-item week would just be noise (set min_items≈3 for weekly).
    """
    buckets: dict[str, list[int]] = defaultdict(list)
    for rec in scored:
        if not rec.get("timestamp"):
            continue
        buckets[bucket_key(rec["timestamp"], period)].append(rec["score"])

    readings = []
    for key in sorted(buckets):
        scores = buckets[key]
        if len(scores) < min_items:
            continue
        readings.append(
            {"period": key, "consensus": round(sum(scores) / len(scores), 1), "n": len(scores)}
        )
    return readings


def aggregate_by_month(scored: list[dict]) -> list[dict]:
    """Backward-compatible monthly wrapper (Slice-1 demo uses the 'month' key)."""
    return [{"month": r["period"], "consensus": r["consensus"], "n": r["n"]}
            for r in aggregate_by_period(scored, "month")]
