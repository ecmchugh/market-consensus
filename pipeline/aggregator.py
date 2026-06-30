"""Weighted consensus aggregation — the core intelligence of the system.

Turns a list of per-item sentiment scores into one daily reading, weighting
each item by source authority, recency, and engagement, and flagging days
where sources disagree.

Per-item weight:
    weight = source_weight(tier) * recency_factor * engagement_factor

- source_weight: from config (news > reddit; arXiv = 0.0 → themes only, never
  moves the directional number).
- recency_factor: exponential decay, 0.5 ** (age_hours / half_life). Newer
  content counts more.
- engagement_factor: 1 + k * ln(1 + raw_engagement). Log scale so 50k upvotes
  isn't 1000x a 50-upvote post; non-social content (engagement 0) → factor 1.0.

Daily consensus = weighted average of sentiment over all items.

Conflict detection: compute a weighted mean *per source tier*, then measure the
spread *across tier means*. High spread (e.g. Reddit bullish while news bearish)
flags a "contested" day — surfaced rather than averaged away. Measuring spread
across tiers (not across all items) isolates real cross-source disagreement from
ordinary within-source noise.
"""

import math
from collections import Counter, defaultdict
from datetime import datetime, timezone

import config

# Sentiment within +/- this band reads as neutral rather than bull/bear.
LABEL_NEUTRAL_BAND = 0.15


def _age_hours(timestamp, now):
    """Hours between `timestamp` (ISO string) and `now`; clamped at >= 0."""
    if not timestamp:
        return 0.0
    dt = datetime.fromisoformat(timestamp)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def _recency_factor(timestamp, now):
    return 0.5 ** (_age_hours(timestamp, now) / config.RECENCY_HALF_LIFE_HOURS)


def _engagement_factor(raw_engagement):
    return 1.0 + config.ENGAGEMENT_LOG_WEIGHT * math.log1p(max(0, raw_engagement))


def _weight(record, now):
    """Full per-item weight (0.0 for themes-only sources like arXiv)."""
    source_weight = config.SOURCE_WEIGHTS.get(record["source_tier"], 0.0)
    return (
        source_weight
        * _recency_factor(record["timestamp"], now)
        * _engagement_factor(record["raw_engagement"])
    )


def _weighted_mean(pairs):
    """Weighted mean of (weight, value) pairs; 0.0 if no weight."""
    total_w = sum(w for w, _ in pairs)
    if total_w == 0:
        return 0.0
    return sum(w * v for w, v in pairs) / total_w


def _tier_means(scored, now):
    """Weighted mean sentiment per directional tier (excludes 0-weight tiers)."""
    by_tier = defaultdict(list)
    for rec in scored:
        if config.SOURCE_WEIGHTS.get(rec["source_tier"], 0.0) > 0:
            by_tier[rec["source_tier"]].append(rec)

    return {
        tier: _weighted_mean([(_weight(r, now), r["sentiment_score"]) for r in recs])
        for tier, recs in by_tier.items()
    }


def _dispersion(values):
    """Population standard deviation; 0.0 with fewer than two values."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _label(score):
    if score > LABEL_NEUTRAL_BAND:
        return "bullish"
    if score < -LABEL_NEUTRAL_BAND:
        return "bearish"
    return "neutral"


def _confidence(spread):
    """Lower sentiment spread = more agreement = higher confidence."""
    if spread <= config.CONFIDENCE_HIGH_MAX:
        return "high"
    if spread <= config.CONFIDENCE_MED_MAX:
        return "medium"
    return "low"


def _ticker_consensus(scored, now):
    """Per-ticker weighted consensus, built from directional sources only.

    arXiv (themes-only, weight 0) doesn't drive ticker direction, so we skip it
    here even though its themes still surface at the top level. Tickers with
    fewer than MIN_TICKER_MENTIONS directional mentions are dropped as noise.
    """
    by_ticker = defaultdict(list)
    for rec in scored:
        if config.SOURCE_WEIGHTS.get(rec["source_tier"], 0.0) <= 0:
            continue
        for ticker in rec.get("tickers", []):
            key = ticker.strip().upper()
            if key:
                by_ticker[key].append(rec)

    results = []
    for ticker, recs in by_ticker.items():
        if len(recs) < config.MIN_TICKER_MENTIONS:
            continue
        score = _weighted_mean(
            [(_weight(r, now), r["sentiment_score"]) for r in recs]
        )
        # Confidence from how much the individual scores agree.
        spread = _dispersion([r["sentiment_score"] for r in recs])
        results.append({
            "ticker": ticker,
            "score": round(score, 4),
            "label": _label(score),
            "mentions": len(recs),
            "confidence": _confidence(spread),
        })

    # Strongest signals first (most bullish or most bearish).
    results.sort(key=lambda d: abs(d["score"]), reverse=True)
    return results


def _top_themes(scored, n=10):
    """Rank themes by frequency across all items (arXiv included)."""
    counts, display = Counter(), {}
    for rec in scored:
        for theme in rec.get("themes", []):
            key = theme.strip().lower()
            if not key:
                continue
            counts[key] += 1
            display.setdefault(key, theme.strip())
    return [(display[k], c) for k, c in counts.most_common(n)]


def _collect_signals(scored, field, n=10):
    """Gather unique bull/bear signals (preserving order) up to n."""
    seen, out = set(), []
    for rec in scored:
        for sig in rec.get(field, []):
            key = sig.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(sig.strip())
            if len(out) >= n:
                return out
    return out


def aggregate(scored, now=None):
    """Compute the daily consensus from scored records.

    `now` is injectable for deterministic testing; defaults to current UTC.
    """
    now = now or datetime.now(timezone.utc)

    weights = [_weight(rec, now) for rec in scored]
    consensus = _weighted_mean(
        [(w, rec["sentiment_score"]) for w, rec in zip(weights, scored)]
    )

    tier_means = _tier_means(scored, now)
    dispersion = _dispersion(list(tier_means.values()))

    # Confidence measures cross-source *agreement*, so it's only meaningful with
    # >= 2 directional tiers. With one tier the spread is trivially 0.0 — report
    # that honestly instead of passing it off as "high confidence".
    n_tiers = len(tier_means)
    if n_tiers >= 2:
        confidence = _confidence(dispersion)
    elif n_tiers == 1:
        confidence = "single-source"
    else:
        confidence = "none"

    return {
        "consensus_score": round(consensus, 4),
        "label": _label(consensus),
        "confidence": confidence,
        "item_count": len(scored),
        "contributing_count": sum(1 for w in weights if w > 0),
        "tier_means": {t: round(v, 4) for t, v in sorted(tier_means.items())},
        "dispersion": round(dispersion, 4),
        "contested": dispersion > config.CONFLICT_STDDEV_THRESHOLD,
        "tickers": _ticker_consensus(scored, now),
        "top_themes": _top_themes(scored),
        "bull_signals": _collect_signals(scored, "bull_signals"),
        "bear_signals": _collect_signals(scored, "bear_signals"),
    }
