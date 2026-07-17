"""Slice 2 — breadth backtest: does the mood read predict price, across many names?

Slice 1 proved the loop on one subject but could only *hint* at the signal (n=11
months → correlations not significant). Slice 2 runs the SAME engine across a basket
of subjects and pools the evidence, so the lead/lag relationship either becomes
statistically real or is shown to be noise.

Method (honest about the stats):
  * For each subject: fetch HN → score stance (concurrent) → monthly conviction →
    monthly price return.
  * Build three aligned pairings per subject:
        coincident : conviction[t]      vs return[t]
        LEAD       : conviction[t]      vs return[t+1]   (mood predicts next month?)
        lag        : conviction[t]      vs return[t-1]   (price drives mood?)
  * DEMEAN within each subject before pooling, so a subject's baseline mood/return
    level can't create a spurious cross-subject correlation. Then pool all pairs and
    compute Pearson r + a t-stat (|t|>~2 ⇒ significant at ~0.05).
  * Also report the per-subject distribution (how many subjects show a positive lead).

Caching: each subject's scored items are cached under .slice2_cache/ so re-runs (or a
crash midway) skip re-fetching/re-scoring — scoring is the expensive part.

Run:
    venv/bin/python slice2_backtest.py                 # default basket
    venv/bin/python slice2_backtest.py --per-month 15 --workers 10
    venv/bin/python slice2_backtest.py --subjects NVDA,AMD,AAPL
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

# Reuse the Slice-1 stages unchanged — same engine, many subjects.
from slice1_prove_loop import (
    aggregate_by_period,
    fetch_hn,
    fetch_price,
    score_stance,
)

CACHE_DIR = Path(".slice2_cache")

# Weekly buckets are much thinner than monthly, so require a few items per week for
# a reading to count — otherwise a 1-post week is just noise.
MIN_ITEMS = {"month": 1, "week": 3}

# Basket: liquid names with real, sustained Hacker News discussion. (ticker, HN query).
# HN talks companies by name, so the query is the company, the proxy is its ticker.
BASKET = [
    ("NVDA", "Nvidia"), ("AMD", "AMD"), ("AAPL", "Apple"), ("MSFT", "Microsoft"),
    ("AMZN", "Amazon"), ("GOOGL", "Google"), ("META", "Meta"), ("TSLA", "Tesla"),
    ("AVGO", "Broadcom"), ("INTC", "Intel"), ("MU", "Micron"), ("QCOM", "Qualcomm"),
    ("ORCL", "Oracle"), ("CRM", "Salesforce"), ("NFLX", "Netflix"), ("ADBE", "Adobe"),
    ("PLTR", "Palantir"), ("COIN", "Coinbase"), ("UBER", "Uber"), ("SHOP", "Shopify"),
    ("SNOW", "Snowflake"), ("ARM", "Arm"), ("SMCI", "Supermicro"), ("DELL", "Dell"),
]

# Crypto basket: attention/narrative-driven and less efficient than large-cap equity —
# where sentiment SHOULD show up if it shows up anywhere. Proxy = yfinance USD pair;
# HN query = the name HN actually uses. (ticker, HN query).
CRYPTO_BASKET = [
    ("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana"),
    ("DOGE-USD", "Dogecoin"), ("XRP-USD", "XRP"), ("ADA-USD", "Cardano"),
    ("AVAX-USD", "Avalanche"), ("LINK-USD", "Chainlink"), ("DOT-USD", "Polkadot"),
    ("LTC-USD", "Litecoin"),
]


def get_basket(universe: str):
    return CRYPTO_BASKET if universe == "crypto" else BASKET


# ----------------------------------------------------------------------------
# Per-subject pipeline (with caching)
# ----------------------------------------------------------------------------
def scored_items_for(ticker: str, hn_query: str, period: str, windows: int,
                     per_window: int, workers: int) -> list[dict]:
    """Fetch + score one subject's HN items, using an on-disk cache."""
    CACHE_DIR.mkdir(exist_ok=True)
    # Key includes period + depth so different configs never collide in the cache.
    cache = CACHE_DIR / f"{ticker}_{period}_{per_window}.json"
    if cache.exists():
        data = json.loads(cache.read_text())
        print(f"  [{ticker}] cache hit: {len(data)} scored items")
        return data

    subject = {"hn_query": hn_query, "proxy": ticker}
    records = fetch_hn(subject, period=period, windows=windows, per_window=per_window)
    scored = score_stance(records, ticker, max_workers=workers, quiet=True)
    cache.write_text(json.dumps(scored))
    print(f"  [{ticker}] fetched {len(records)} → scored {len(scored)} relevant (cached)")
    return scored


def subject_series(ticker: str, scored: list[dict], period: str = "month") -> list[dict] | None:
    """Build aligned per-period (conviction, price-return) rows for one subject."""
    readings = aggregate_by_period(scored, period, min_items=MIN_ITEMS.get(period, 1))
    if len(readings) < 4:  # too few periods to contribute anything meaningful
        return None
    keys = [r["period"] for r in readings]
    start = (min(keys) + "-01") if period == "month" else min(keys)  # week keys are full dates
    prices = fetch_price(ticker, start, datetime.now(timezone.utc).strftime("%Y-%m-%d"), period)
    price_by_key = {p["period"]: p["close"] for p in prices}

    rows = []
    prev_close = None
    conv_by_key = {r["period"]: r["consensus"] for r in readings}
    for k in sorted(set(conv_by_key) & set(price_by_key)):
        close = price_by_key[k]
        ret = None if prev_close is None else (close - prev_close) / prev_close
        rows.append({"period": k, "conviction": conv_by_key[k], "ret": ret})
        prev_close = close
    return rows if len(rows) >= 4 else None


# ----------------------------------------------------------------------------
# Stats
# ----------------------------------------------------------------------------
def _demean(vals: list[float]) -> list[float]:
    m = sum(vals) / len(vals)
    return [v - m for v in vals]


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    vy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return cov / (vx * vy) if vx and vy else None


def t_stat(r: float, n: int) -> float:
    if abs(r) >= 1 or n < 3:
        return float("inf")
    return r * math.sqrt((n - 2) / (1 - r * r))


def pooled_corr(per_subject_pairs: list[tuple[list[float], list[float]]]):
    """Demean each subject's pairs, pool, return (r, n_pairs, t)."""
    xsive: list[float] = []
    ys: list[float] = []
    for conv, ret in per_subject_pairs:
        if len(conv) < 3:
            continue
        xsive.extend(_demean(conv))
        ys.extend(_demean(ret))
    r = pearson(xsive, ys)
    if r is None:
        return None, len(xsive), None
    return r, len(xsive), t_stat(r, len(xsive))


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def build_pairs(series: list[dict], kind: str) -> tuple[list[float], list[float]]:
    """Return (conviction, return) lists for coincident|lead|lag from one subject's rows."""
    conv, ret = [], []
    for i, row in enumerate(series):
        if kind == "coincident":
            c, r = row["conviction"], row["ret"]
        elif kind == "lead":
            c = row["conviction"]
            r = series[i + 1]["ret"] if i + 1 < len(series) else None
        elif kind == "lag":
            c = row["conviction"]
            r = series[i - 1]["ret"] if i - 1 >= 0 else None
        else:
            raise ValueError(kind)
        if c is not None and r is not None:
            conv.append(c)
            ret.append(r)
    return conv, ret


def main() -> int:
    ap = argparse.ArgumentParser(description="Slice 2 — pooled breadth backtest.")
    ap.add_argument("--period", choices=["month", "week"], default="month",
                    help="aggregation resolution (default: month)")
    ap.add_argument("--per-window", type=int, default=15,
                    help="HN items fetched per period (month or week) per subject")
    ap.add_argument("--windows", type=int, default=0,
                    help="how many periods back (0 = auto: 12 months / 52 weeks)")
    ap.add_argument("--workers", type=int, default=10, help="concurrent scoring workers")
    ap.add_argument("--universe", choices=["tech", "crypto"], default="tech",
                    help="which basket to test (default: tech)")
    ap.add_argument("--subjects", help="comma-separated tickers to override the basket")
    args = ap.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set in .env — can't score.")
        return 1

    windows = args.windows or (52 if args.period == "week" else 12)

    if args.subjects:
        want = {s.strip().upper() for s in args.subjects.split(",")}
        lookup = dict(BASKET + CRYPTO_BASKET)
        basket = [(t, lookup.get(t, t)) for t in want]  # fall back to ticker as query
    else:
        basket = get_basket(args.universe)
        if args.universe == "tech" and args.period == "week":
            basket = basket[:10]  # weekly needs high-volume names to populate weeks

    t0 = time.time()
    print(f"\n=== Slice 2 [{args.universe}]: {len(basket)} subjects, {args.period}ly, "
          f"{args.per_window}/{args.period} × {windows}, {args.workers} workers ===\n")

    per_subject = {"coincident": [], "lead": [], "lag": []}
    kept_subjects = 0
    total_items = 0
    for ticker, query in basket:
        scored = scored_items_for(ticker, query, args.period, windows, args.per_window, args.workers)
        total_items += len(scored)
        series = subject_series(ticker, scored, args.period)
        if series is None:
            print(f"  [{ticker}] too sparse, excluded")
            continue
        kept_subjects += 1
        for kind in per_subject:
            conv, ret = build_pairs(series, kind)
            if conv:
                per_subject[kind].append((conv, ret))

    print(f"\n=== pooled results ({kept_subjects} subjects, {total_items} scored items) ===\n")
    print(f"{'relationship':<12} {'r':>7} {'n':>6} {'t':>7}   verdict")
    for kind in ["coincident", "lead", "lag"]:
        r, n, t = pooled_corr(per_subject[kind])
        if r is None:
            print(f"{kind:<12}    n/a")
            continue
        sig = "significant" if abs(t) > 2 else "not significant"
        print(f"{kind:<12} {r:+7.2f} {n:>6} {t:>7.2f}   {sig}")

    # Per-subject lead sign distribution — is the effect consistent across names?
    lead_rs = [pearson(_demean(c), _demean(rt)) for c, rt in per_subject["lead"] if len(c) >= 3]
    lead_rs = [r for r in lead_rs if r is not None]
    if lead_rs:
        pos = sum(1 for r in lead_rs if r > 0)
        print(f"\nper-subject LEAD: {pos}/{len(lead_rs)} subjects positive "
              f"(mean r {sum(lead_rs)/len(lead_rs):+.2f})")

    _plot(per_subject["lead"])
    print(f"\n=== done in {time.time() - t0:.0f}s ===")
    return 0


def _plot(lead_pairs) -> None:
    """Scatter of pooled, demeaned conviction[t] vs next-month return[t+1]."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        return
    xs, ys = [], []
    for conv, ret in lead_pairs:
        if len(conv) >= 3:
            xs.extend(_demean(conv))
            ys.extend([v * 100 for v in _demean(ret)])
    if not xs:
        return
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.axhline(0, color="#c3c9d2", lw=1)
    ax.axvline(0, color="#c3c9d2", lw=1)
    ax.scatter(xs, ys, s=18, alpha=0.5, color="#3E6DDA", edgecolor="none")
    ax.set_xlabel("Conviction this month (demeaned within subject)")
    ax.set_ylabel("Next-month price return %  (demeaned)")
    ax.set_title("Slice 2 — does mood lead price? (pooled across basket)", fontweight="bold", loc="left")
    fig.savefig("slice2_lead_scatter.png", dpi=130, bbox_inches="tight")
    print("  scatter → slice2_lead_scatter.png")


if __name__ == "__main__":
    raise SystemExit(main())
