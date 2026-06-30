"""Market Consensus — full pipeline entry point.

    scrape  ->  normalize  ->  score (Claude)  ->  aggregate  ->  print

Scraping and normalization always run. Scoring + aggregation run when
ANTHROPIC_API_KEY is set; otherwise we print the normalized feed by tier and
explain what's missing — so the pipeline is useful even before the key is added.

Usage:
    python3 main.py            # synchronous scoring (fast dev loop)
    python3 main.py --batch    # Batch API scoring (~50% cheaper daily run)
"""

import argparse
import os
from collections import Counter
from datetime import datetime, timezone

from pipeline import aggregator, normalizer, scorer
from scrapers import arxiv, news, reddit

SCRAPERS = {
    "reddit": reddit.scrape,
    "news": news.scrape,
    "arxiv": arxiv.scrape,
}

TIER_NAMES = {1: "arxiv", 2: "news", 3: "reddit"}


def run_scrapers():
    """Run every scraper; one failing source never kills the run."""
    raw = []
    for name, scrape_fn in SCRAPERS.items():
        print(f"scraping {name} ...")
        try:
            records = scrape_fn()
            print(f"  -> {len(records)} records")
            raw.extend(records)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {name} failed: {exc}")
    return raw


def print_tier_breakdown(records):
    """Counts by tier — shown when we can't score yet."""
    counts = Counter(TIER_NAMES.get(r["source_tier"], "?") for r in records)
    print("\nNormalized feed by source:")
    for name, n in counts.most_common():
        print(f"  {name:8} {n}")


def print_consensus(result):
    """Pretty-print the daily consensus report."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bar = "=" * 70
    print(f"\n{bar}")
    print(f"DAILY MARKET CONSENSUS — {today}")
    print(bar)
    conf = result["confidence"]
    if conf in ("high", "medium", "low"):
        conf_str = f"{conf} confidence"
    elif conf == "single-source":
        conf_str = "single source — agreement not assessable"
    else:
        conf_str = "no directional signal"
    print(f"Consensus: {result['consensus_score']:+.3f}  "
          f"({result['label'].upper()}, {conf_str})")
    print(f"Items: {result['item_count']} scored, "
          f"{result['contributing_count']} directional")

    if len(result["tier_means"]) >= 2:
        state = "CONTESTED" if result["contested"] else "aligned"
        print(f"\nSource disagreement: {result['dispersion']:.3f}  ({state})")
    else:
        print("\nSource disagreement: n/a (need ≥ 2 source tiers)")
    for tier, mean in result["tier_means"].items():
        print(f"  {TIER_NAMES.get(tier, tier):8} {mean:+.3f}")

    if result.get("tickers"):
        print("\nPer-ticker consensus:")
        for t in result["tickers"]:
            print(f"  {t['ticker']:6} {t['score']:+.3f}  {t['label']:8}"
                  f"  ({t['mentions']} mentions, {t['confidence']} confidence)")

    if result["top_themes"]:
        print("\nTop themes:")
        for theme, count in result["top_themes"]:
            print(f"  - {theme} ({count})")

    if result["bull_signals"]:
        print("\nBull signals:")
        for sig in result["bull_signals"]:
            print(f"  + {sig}")

    if result["bear_signals"]:
        print("\nBear signals:")
        for sig in result["bear_signals"]:
            print(f"  - {sig}")
    print(bar)


def main():
    parser = argparse.ArgumentParser(description="Market Consensus daily pipeline")
    parser.add_argument(
        "--batch", action="store_true",
        help="use the Batch API for scoring (cheaper, async)",
    )
    args = parser.parse_args()

    raw = run_scrapers()
    records = normalizer.normalize(raw)
    print(f"\nnormalized {len(records)} records")

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("\nANTHROPIC_API_KEY not set — skipping scoring & aggregation.")
        print("Add it to .env to produce the consensus report.")
        print_tier_breakdown(records)
        return

    mode = "batch" if args.batch else "sync"
    print(f"\nscoring {len(records)} records ({mode}) ...")
    scored = scorer.score(records, use_batch=args.batch)
    result = aggregator.aggregate(scored)
    print_consensus(result)


if __name__ == "__main__":
    main()
