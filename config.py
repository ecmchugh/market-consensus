"""Central configuration — every tunable constant lives here.

Keeping the magic numbers in one place means tuning the consensus algorithm is
editing this file, not hunting through pipeline logic.
"""

# --- Sources & tiers -------------------------------------------------------
# Tier identifies a source's authority class (lower = more authoritative).
# Matched by prefix, so "reddit/r/investing" and "reddit/r/stocks" both → 3.
SOURCE_TIERS = (
    ("arxiv", 1),
    ("yahoo-finance", 2),
    ("reddit", 3),
)
DEFAULT_TIER = 3


# --- Directional weighting (used by the aggregator) ------------------------
# How much each tier contributes to the daily *directional* (bull/bear) score.
# These are relative; the aggregator normalizes them.
#
# NOTE: arXiv (tier 1) is a *themes-only* source — weight 0.0 means it never
# moves the directional number, but its content is still scored and its themes
# are still surfaced. News is the most authoritative directional source.
SOURCE_WEIGHTS = {
    1: 0.0,   # arxiv  — themes only, no directional contribution
    2: 1.0,   # news   — most authoritative directional signal
    3: 0.6,   # reddit — crowd signal, discounted vs. news
}

# Recency: content decays with an exponential half-life. Runs once daily, so
# everything is <24h old; 12h half-life ≈ recent items count ~2x older ones.
RECENCY_HALF_LIFE_HOURS = 12.0

# Engagement boosts a Reddit post's weight on a log scale (50k upvotes isn't
# 1000x a 50-upvote post). factor = 1 + ENGAGEMENT_LOG_WEIGHT * ln(1 + score).
# Non-social sources have score 0 → ln(1+0)=0 → factor 1.0 (no distortion).
ENGAGEMENT_LOG_WEIGHT = 0.15

# Conflict detection: if the spread of weighted sentiment *across tiers*
# exceeds this, the day is flagged "contested" and the disagreement surfaced.
# (Placeholder — tuned when we build the aggregator in step 5.)
CONFLICT_STDDEV_THRESHOLD = 0.4


# --- Claude scorer ---------------------------------------------------------
MODEL = "claude-opus-4-8"
