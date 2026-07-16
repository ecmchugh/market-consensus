"""Slice 1 — prove the loop (Reddit-first, one subject).

The whole point: run the ENTIRE vertical end-to-end on a single subject and see
whether "what Reddit says" tracks "what the price did." If it does — even weakly —
the core idea holds and everything else is widening/deepening (see docs/BUILD_PLAN.md).

This is deliberately the GENERAL engine, parameterized by subject: the same code
that runs on NVDA runs on any ticker. NVDA is just the first thing we point it at,
because it has huge Reddit volume and a clean ground truth (its own stock price).

The stages (each will graduate into its own module later — noted inline):
    fetch  →  filter to subject  →  score stance  →  aggregate  →  chart vs price
    reddit    (search query)        Claude Haiku     by month      yfinance

Run:
    venv/bin/python slice1_prove_loop.py NVDA
    venv/bin/python slice1_prove_loop.py TSLA --ticker TSLA

Notes / honest limitations for Slice 1:
  * We pull Reddit *search, top-of-year* to get subject-specific posts with real
    timestamps spread across time. "Top" is engagement-biased (not a representative
    daily sample), which is fine for the Slice-1 bar ("does the loop work + is there
    any signal"). Slice 2 replaces this with proper day-by-day accumulation.
  * No Reddit OAuth needed — uses the public search RSS. With OAuth (Slice 1.5) we'd
    get upvote/comment counts for engagement weighting and more posts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import feedparser

# Reuse the scrapers' shared helpers (loads .env on import, polite rate-limited GET).
from scrapers.utils import USER_AGENT, polite_get, to_iso

# ----------------------------------------------------------------------------
# Subject registry. A subject = what the user asks about + how to find it on
# Reddit + its tradeable proxy for the price overlay. This is the seed of the
# general "resolve any subject → query + proxy" layer (Slice 4).
# ----------------------------------------------------------------------------
SUBJECTS = {
    "NVDA": {
        "query": "NVDA OR Nvidia",
        "proxy": "NVDA",
        "subreddits": ["wallstreetbets", "stocks", "investing", "NVDA_Stock"],
    },
    "TSLA": {
        "query": "TSLA OR Tesla",
        "proxy": "TSLA",
        "subreddits": ["wallstreetbets", "stocks", "investing", "teslainvestorsclub"],
    },
}

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

MODEL = "claude-haiku-4-5"  # cheap + fast for high-volume per-item scoring (cost discipline)


# ============================================================================
# STAGE 1 — FETCH  (→ future ingestion/reddit_search.py)
# ============================================================================
def fetch_reddit_posts(subject: dict, per_sub: int = 100) -> list[dict]:
    """Fetch subject-specific posts via Reddit's public search RSS (no OAuth).

    We search each subreddit for the subject, sorted by top over the past year,
    so we get real posts with real timestamps spread across time.
    """
    records: list[dict] = []
    seen_urls: set[str] = set()

    for sub in subject["subreddits"]:
        url = f"https://www.reddit.com/r/{sub}/search.rss"
        params = {
            "q": subject["query"],
            "restrict_sr": "1",   # search within this subreddit only
            "sort": "top",
            "t": "year",
            "limit": str(per_sub),
        }
        try:
            resp = polite_get(url, params=params, headers={"User-Agent": BROWSER_UA})
        except Exception as e:  # noqa: BLE001 — one bad sub shouldn't kill the run
            print(f"  ! r/{sub}: fetch failed ({e.__class__.__name__}), skipping")
            continue

        feed = feedparser.parse(resp.content)
        n_before = len(records)
        for entry in feed.entries:
            link = entry.get("link", "")
            if link in seen_urls:
                continue
            seen_urls.add(link)

            ts = None
            if entry.get("published_parsed"):
                import calendar
                ts = to_iso(calendar.timegm(entry["published_parsed"]))

            title = entry.get("title", "")
            # feedparser gives an HTML summary; strip tags crudely for the model.
            summary = entry.get("summary", "") or ""
            records.append(
                {
                    "source": f"reddit/r/{sub}",
                    "title": title,
                    "text": _strip_html(summary) or title,
                    "url": link,
                    "timestamp": ts,
                }
            )
        print(f"  r/{sub}: +{len(records) - n_before} posts")

    return records


def _strip_html(s: str) -> str:
    """Very light tag strip — enough to hand clean text to the model."""
    import re
    text = re.sub(r"<[^>]+>", " ", s)
    text = re.sub(r"&#\d+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ============================================================================
# STAGE 2 + 3 — FILTER TO SUBJECT + SCORE STANCE  (→ future pipeline/stance.py)
# ============================================================================
# The rubric lives in the system prompt so it's identical for every item
# (reproducibility) and gets prompt-cached across the batch (cost). This is the
# Haiku-for-volume half of the cost split; Sonnet-once-per-query comes in Slice 4.
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


def score_stance(records: list[dict], subject_name: str) -> list[dict]:
    """Score each record's stance with Claude Haiku. Adds 'score'/'relevant'/'rationale'.

    Returns only the records the model judged relevant to the subject.
    """
    from anthropic import Anthropic

    client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    scored: list[dict] = []
    n = len(records)
    cache_hits = 0

    for i, rec in enumerate(records, 1):
        content = f"SUBJECT: {subject_name}\n\nPOST TITLE: {rec['title']}\n\nPOST BODY: {rec['text'][:1500]}"
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=120,
                system=[
                    {
                        "type": "text",
                        "text": STANCE_SYSTEM,
                        # Cache the (large, fixed) rubric so every call after the
                        # first in the batch reads it from cache, not fresh tokens.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {"role": "user", "content": content},
                    {"role": "assistant", "content": "{"},  # prefill → forces clean JSON
                ],
            )
            cache_hits += getattr(resp.usage, "cache_read_input_tokens", 0) or 0
            raw = "{" + resp.content[0].text
            data = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{n}] scoring error ({e.__class__.__name__}), skipping")
            continue

        if not data.get("relevant"):
            continue
        rec = {**rec, "score": int(data["score"]), "rationale": data.get("rationale", "")}
        scored.append(rec)
        if i % 10 == 0 or i == n:
            print(f"  scored {i}/{n} … kept {len(scored)} relevant")

    print(f"  (prompt-cache read tokens across batch: {cache_hits:,})")
    return scored


# ============================================================================
# STAGE 4 — AGGREGATE  (→ future pipeline/aggregate.py)
# ============================================================================
def aggregate_by_month(scored: list[dict]) -> list[dict]:
    """Roll scored posts into a monthly conviction reading.

    Equal-weighted for Slice 1 (RSS has no engagement metadata). Slice 1.5 adds
    upvote/comment weighting via config.ENGAGEMENT_LOG_WEIGHT once OAuth is on.
    """
    buckets: dict[str, list[int]] = defaultdict(list)
    for rec in scored:
        if not rec.get("timestamp"):
            continue
        month = rec["timestamp"][:7]  # YYYY-MM
        buckets[month].append(rec["score"])

    readings = []
    for month in sorted(buckets):
        scores = buckets[month]
        readings.append(
            {
                "month": month,
                "consensus": round(sum(scores) / len(scores), 1),
                "n": len(scores),
            }
        )
    return readings


# ============================================================================
# STAGE 5 — PRICE  (→ future analysis/prices.py)
# ============================================================================
def fetch_monthly_price(ticker: str, start: str, end: str) -> list[dict]:
    """Monthly close for the proxy over the reading window (yfinance, no key)."""
    import yfinance as yf

    df = yf.download(ticker, start=start, end=end, interval="1mo", progress=False, auto_adjust=True)
    out = []
    if df is None or df.empty:
        return out
    closes = df["Close"]
    # yfinance may return a single-column DataFrame; squeeze to a Series.
    if hasattr(closes, "columns"):
        closes = closes.iloc[:, 0]
    for idx, val in closes.items():
        out.append({"month": idx.strftime("%Y-%m"), "close": round(float(val), 2)})
    return out


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
    ax1.set_ylabel("Reddit conviction\n(−100…+100)")
    ax1.set_title(f"Market Consensus — Slice 1: does the Reddit read track the price?  ·  {subject_name}",
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

    print("1) fetch reddit posts")
    records = fetch_reddit_posts(subject)
    print(f"   → {len(records)} unique posts\n")
    if not records:
        print("No posts fetched (Reddit may be rate-limiting this IP). Try again, or add OAuth creds.")
        return 1
    if args.limit:
        records = records[: args.limit]
        print(f"   (capped to {len(records)} for a cheap run)\n")

    print("2/3) filter to subject + score stance (Claude Haiku)")
    scored = score_stance(records, key)
    print(f"   → {len(scored)} relevant scored posts\n")
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
