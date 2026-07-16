"""Slice 2 — significance & robustness, run on the cached scores (no LLM calls).

The main backtest reports a pooled lead correlation and a textbook t-stat. But with
only ~12 months per subject, a t-stat leans on assumptions (normality, independence)
that monthly market data violates, and small samples inflate correlations. This
script stress-tests the headline number three honest ways:

  1. PERMUTATION NULL — the real test. Repeatedly shuffle each subject's return
     series to destroy the true time-alignment between conviction[t] and
     return[t+1], recompute the pooled correlation, and build the null distribution.
     The empirical p-value = fraction of shuffles at least as extreme as the real r.
     Makes no distributional assumptions.

  2. BOOTSTRAP OVER SUBJECTS — resample the basket with replacement to get a 95% CI
     on the pooled r. Answers "is this driven by a few lucky names?"

  3. HORIZON SWEEP — lead at t+1 vs t+2. A real signal typically decays smoothly; a
     fluke does whatever it wants.

Runs on .slice2_cache/*.json — so only meaningful AFTER slice2_backtest.py has filled
the cache. Reuses the exact series/pairing logic from the backtest so the numbers match.

Run:
    venv/bin/python slice2_analysis.py --per-month 15 --iters 5000
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from slice2_backtest import (
    BASKET,
    CACHE_DIR,
    _demean,
    pearson,
    subject_series,
)


def _load_cached_series(period: str, per_window: int, horizon: int):
    """Return {ticker: (conviction[], return_at_horizon[])} from cached scores."""
    out = {}
    for ticker, _q in BASKET:
        cache = CACHE_DIR / f"{ticker}_{period}_{per_window}.json"
        if not cache.exists():
            continue
        import json
        scored = json.loads(cache.read_text())
        series = subject_series(ticker, scored, period)
        if not series:
            continue
        conv, ret = [], []
        for i, row in enumerate(series):
            j = i + horizon
            if j < len(series) and row["conviction"] is not None and series[j]["ret"] is not None:
                conv.append(row["conviction"])
                ret.append(series[j]["ret"])
        if len(conv) >= 3:
            out[ticker] = (conv, ret)
    return out


def _pooled_r(subject_pairs) -> float | None:
    """Pooled, within-subject-demeaned Pearson r over a dict of ticker -> (conv, ret)."""
    xs, ys = [], []
    for conv, ret in subject_pairs.values():
        xs.extend(_demean(conv))
        ys.extend(_demean(ret))
    return pearson(xs, ys)


def permutation_test(subject_pairs, iters: int) -> tuple[float, float]:
    """Return (observed r, empirical two-sided p) via per-subject return shuffles."""
    observed = _pooled_r(subject_pairs)
    if observed is None:
        return 0.0, 1.0
    hits = 0
    for _ in range(iters):
        shuffled = {}
        for t, (conv, ret) in subject_pairs.items():
            r2 = ret[:]
            random.shuffle(r2)  # break the real conviction↔next-return alignment
            shuffled[t] = (conv, r2)
        r = _pooled_r(shuffled)
        if r is not None and abs(r) >= abs(observed):
            hits += 1
    return observed, (hits + 1) / (iters + 1)  # +1 = never report p=0


def bootstrap_ci(subject_pairs, iters: int) -> tuple[float, float]:
    """95% CI for the pooled r by resampling subjects with replacement."""
    tickers = list(subject_pairs)
    rs = []
    for _ in range(iters):
        pick = {i: subject_pairs[random.choice(tickers)] for i in range(len(tickers))}
        r = _pooled_r(pick)
        if r is not None:
            rs.append(r)
    rs.sort()
    if not rs:
        return (0.0, 0.0)
    lo = rs[int(0.025 * len(rs))]
    hi = rs[int(0.975 * len(rs))]
    return lo, hi


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=["month", "week"], default="month")
    ap.add_argument("--per-window", type=int, default=15)
    ap.add_argument("--iters", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    random.seed(args.seed)

    cached = list(Path(CACHE_DIR).glob(f"*_{args.period}_{args.per_window}.json")) if CACHE_DIR.exists() else []
    if not cached:
        print(f"No cache for period={args.period}, per_window={args.per_window}. Run slice2_backtest.py first.")
        return 1

    print(f"\n=== Slice 2 significance ({args.period}ly, per_window={args.per_window}, {args.iters} iters) ===\n")

    # Headline: LEAD (t+1).
    lead = _load_cached_series(args.period, args.per_window, horizon=1)
    print(f"subjects with usable series: {len(lead)}")
    obs, p = permutation_test(lead, args.iters)
    lo, hi = bootstrap_ci(lead, args.iters)
    per_subj = [pearson(_demean(c), _demean(r)) for c, r in lead.values()]
    per_subj = [r for r in per_subj if r is not None]
    pos = sum(1 for r in per_subj if r > 0)

    print("\nLEAD  conviction[t] → return[t+1]")
    print(f"  pooled r          {obs:+.3f}")
    print(f"  permutation p     {p:.4f}   ({'significant' if p < 0.05 else 'NOT significant'} at .05)")
    print(f"  bootstrap 95% CI  [{lo:+.3f}, {hi:+.3f}]   ({'excludes' if lo > 0 or hi < 0 else 'includes'} zero)")
    print(f"  per-subject sign  {pos}/{len(per_subj)} positive")

    # Horizon sweep — does it decay like a real signal?
    print("\nhorizon sweep (pooled r):")
    for h in (0, 1, 2):
        pairs = _load_cached_series(args.period, args.per_window, horizon=h)
        r = _pooled_r(pairs)
        label = {0: "t   (coincident)", 1: "t+1 (lead)", 2: "t+2 (lead)"}[h]
        print(f"  {label:<18} {r:+.3f}" if r is not None else f"  {label:<18} n/a")

    print("\ninterpretation: trust the permutation p over the t-stat; the CI shows")
    print("robustness to subject choice; a smooth horizon decay argues for a real (if")
    print("weak) effect, a jagged one argues for noise.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
