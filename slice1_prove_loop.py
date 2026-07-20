"""Slice 1 — prove the loop (source-pluggable, one subject).

The whole point: run the ENTIRE vertical end-to-end on a single subject and see
whether "what the conversation says" tracks "what the price did." If it does — even
weakly — the core idea holds and everything else is widening/deepening (see
docs/BUILD_PLAN.md).

As of the Phase-1 graduation (2026-07), the engine stages live in reusable modules
and this file is a THIN ORCHESTRATOR — subject registry + price + chart + CLI:
    fetch  →  filter to subject  →  score stance  →  aggregate  →  chart vs price
  ingestion.sources   (relevance)    pipeline.stance   pipeline.aggregate   yfinance

Sources are pluggable and each item carries a `source_type`:
    * "informed" — practitioners/technical crowd (Hacker News). No credentials.
    * "crowd"    — retail public (Reddit). Needs OAuth for good volume.
The DIVERGENCE between them becomes a headline signal later.

Run:
    venv/bin/python slice1_prove_loop.py NVDA                 # HN (default)
    venv/bin/python slice1_prove_loop.py SEMIS               # semiconductors → SOXX
    venv/bin/python slice1_prove_loop.py NVDA --source reddit # needs Reddit creds
    venv/bin/python slice1_prove_loop.py NVDA --source both
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

# The engine now lives in reusable modules (Phase-1 graduation). Imported here so
# this script stays a thin orchestrator — and re-exported so `slice2_backtest.py`
# (which imports fetch_hn / score_stance / aggregate_by_period / fetch_price from
# this module) keeps working unchanged.
from ingestion.sources import fetch_hn, fetch_hn_posts, fetch_reddit_posts  # noqa: F401
from pipeline.aggregate import aggregate_by_month, aggregate_by_period  # noqa: F401
from pipeline.stance import score_stance  # noqa: F401

# ----------------------------------------------------------------------------
# Subject registry. A subject = what the user asks about + how to find it on
# each source + its tradeable proxy for the price overlay. This hardcoded seed is
# replaced by the LLM subject-resolver in Phase 2 (any string → terms + proxy).
# ----------------------------------------------------------------------------
SUBJECTS = {
    "NVDA": {
        "hn_query": "Nvidia",                 # HN discusses the company by name, not ticker
        "reddit_query": "NVDA OR Nvidia",
        "proxy": "NVDA",
        "subreddits": ["wallstreetbets", "stocks", "investing", "NVDA_Stock"],
    },
    "SEMIS": {
        "hn_query": "semiconductor",
        "reddit_query": "semiconductor OR semis OR chips",
        "proxy": "SOXX",                      # semiconductor ETF = the sector's price
        "subreddits": ["stocks", "investing", "semiconductors"],
    },
    "TSLA": {
        "hn_query": "Tesla",
        "reddit_query": "TSLA OR Tesla",
        "proxy": "TSLA",
        "subreddits": ["wallstreetbets", "stocks", "investing", "teslainvestorsclub"],
    },
}


# ============================================================================
# STAGE 5 — PRICE  (→ future analysis/prices.py)
# ============================================================================
def fetch_price(ticker: str, start: str, end: str, period: str = "month") -> list[dict]:
    """Per-period close for the proxy (yfinance, no key). Key: 'period'.

    Weekly bars are indexed by the week's Monday and monthly by the 1st, matching
    the bucket keys from aggregate_by_period so the two join cleanly.
    """
    import yfinance as yf

    interval = "1wk" if period == "week" else "1mo"
    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
    out = []
    if df is None or df.empty:
        return out
    closes = df["Close"]
    if hasattr(closes, "columns"):  # squeeze single-column frame to a Series
        closes = closes.iloc[:, 0]
    for idx, val in closes.items():
        key = idx.strftime("%Y-%m") if period == "month" else idx.strftime("%Y-%m-%d")
        out.append({"period": key, "close": round(float(val), 2)})
    return out


def fetch_monthly_price(ticker: str, start: str, end: str) -> list[dict]:
    """Backward-compatible monthly wrapper (Slice-1 demo uses the 'month' key)."""
    return [{"month": r["period"], "close": r["close"]}
            for r in fetch_price(ticker, start, end, "month")]


# ============================================================================
# STAGE 6 — CHART + LOOK AT IT
# ============================================================================
def make_chart(subject_name: str, readings: list[dict], prices: list[dict], out_path: str) -> None:
    """Two stacked panels sharing the x-axis: conviction (top), price (bottom).

    Two panels, NOT a dual-axis chart — dual y-axes distort correlation. Sharing
    the x lets you honestly eyeball whether mood leads/lags/tracks price.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    r_months = [r["month"] for r in readings]
    r_vals = [r["consensus"] for r in readings]
    p_months = [p["month"] for p in prices]
    p_vals = [p["close"] for p in prices]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"hspace": 0.12})

    ax1.axhline(0, color="#c3c9d2", lw=1, ls="--")
    ax1.plot(r_months, r_vals, color="#3E6DDA", lw=2, marker="o", ms=5)
    ax1.fill_between(r_months, r_vals, 0, color="#3E6DDA", alpha=0.10)
    ax1.set_ylabel("Conviction\n(−100…+100)")
    ax1.set_title(f"Market Consensus — Slice 1: does the read track the price?  ·  {subject_name}",
                  loc="left", fontsize=12, fontweight="bold")
    ax1.set_ylim(-100, 100)
    for r in readings:  # annotate sample size so sparse months are visible
        ax1.annotate(f"n={r['n']}", (r["month"], r["consensus"]),
                     textcoords="offset points", xytext=(0, 8), ha="center", fontsize=7, color="#8791a0")

    ax2.plot(p_months, p_vals, color="#17A673", lw=2, marker="o", ms=4)
    ax2.set_ylabel(f"{subject_name} price\n(monthly close $)")
    ax2.grid(True, axis="y", color="#eef0f3", lw=1)

    all_months = sorted(set(r_months) | set(p_months))
    ax2.set_xticks(all_months[::max(1, len(all_months) // 12)])
    plt.setp(ax2.get_xticklabels(), rotation=45, ha="right", fontsize=8)
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    print(f"\n  chart written → {out_path}")


# ============================================================================
# ORCHESTRATION
# ============================================================================
def main() -> int:
    parser = argparse.ArgumentParser(description="Slice 1 — prove the loop on one subject.")
    parser.add_argument("subject", nargs="?", default="NVDA", help="subject key (default: NVDA)")
    parser.add_argument("--source", choices=["hn", "reddit", "both"], default="hn",
                        help="opinion source (default: hn — zero-auth, 'informed' slice)")
    parser.add_argument("--ticker", help="override the price proxy ticker")
    parser.add_argument("--limit", type=int, default=0, help="cap posts scored (0 = no cap; useful for a cheap smoke test)")
    args = parser.parse_args()

    key = args.subject.upper()
    if key not in SUBJECTS:
        print(f"Unknown subject '{key}'. Known: {', '.join(SUBJECTS)}")
        return 1
    subject = dict(SUBJECTS[key])
    if args.ticker:
        subject["proxy"] = args.ticker.upper()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set in .env — stance scoring can't run.")
        return 1

    t0 = time.time()
    print(f"\n=== Slice 1: {key}  (proxy {subject['proxy']}) ===\n")

    print(f"1) fetch posts  (source: {args.source})")
    records: list[dict] = []
    if args.source in ("hn", "both"):
        records += fetch_hn_posts(subject)
    if args.source in ("reddit", "both"):
        records += fetch_reddit_posts(subject)
    print(f"   → {len(records)} unique items")
    by_type = defaultdict(int)
    for r in records:
        by_type[r.get("source_type", "?")] += 1
    print(f"   breakdown: {dict(by_type)}\n")
    if not records:
        print("No items fetched. (Reddit needs OAuth / may rate-limit; HN should always work.)")
        return 1
    if args.limit:
        records = records[: args.limit]
        print(f"   (capped to {len(records)} for a cheap run)\n")

    print("2/3) filter to subject + score stance (Claude Haiku)")
    scored = score_stance(records, key)
    kept_by_type = defaultdict(int)
    for r in scored:
        kept_by_type[r.get("source_type", "?")] += 1
    print(f"   → {len(scored)} relevant scored items  {dict(kept_by_type)}\n")
    if not scored:
        print("Nothing scored relevant — can't aggregate. Widen subreddits or check the query.")
        return 1

    print("4) aggregate by month")
    readings = aggregate_by_month(scored)
    for r in readings:
        bar = "+" if r["consensus"] >= 0 else "−"
        print(f"   {r['month']}  {bar}{abs(r['consensus']):5.1f}   (n={r['n']})")
    print()

    months = [r["month"] for r in readings]
    start = min(months) + "-01"
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"5) fetch {subject['proxy']} price  ({start} → {end})")
    prices = fetch_monthly_price(subject["proxy"], start, end)
    print(f"   → {len(prices)} monthly closes\n")

    print("6) chart")
    out_path = f"slice1_{key.lower()}.png"
    make_chart(key, readings, prices, out_path)

    # Persist the raw scored items so we can inspect / reuse (seed of the item table).
    with open(f"slice1_{key.lower()}_scored.json", "w") as f:
        json.dump({"subject": key, "readings": readings, "scored": scored, "prices": prices}, f, indent=2)

    print(f"\n=== done in {time.time() - t0:.0f}s ===")
    print("Now LOOK at the chart: does conviction track / lead / lag the price? Write it down.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
