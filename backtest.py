"""Backtest — does the daily news-sentiment signal predict next-day market moves?

Historical replay: we can't backtest on our own saved data (we have ~1 day), so
we manufacture a score history from a past dated-headlines dataset, run it
through the SAME scorer + aggregator the live pipeline uses, then check the
daily consensus score against the next day's index return.

Dataset: Combined_News_DJIA (data/combined_news_djia.csv) — 25 daily headlines
2008-2016 with a DJIA up/down label. IMPORTANT CAVEATS:
  * These are *general* world-news headlines (r/worldnews), not the financial
    news the live system scrapes — so this validates the METHOD, not the exact
    production signal.
  * It's in-sample, single-asset, ignores transaction costs. A hint here means
    "worth a fidelity pass on financial data", not "deploy it".

Usage:
    python3 backtest.py --year 2015 --max-days 5      # cheap sync smoke test
    python3 backtest.py --year 2015 --batch           # full year via Batch API
"""

import argparse
import ast
import math
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from pipeline import aggregator, scorer

DATASET = "data/combined_news_djia.csv"
INDEX_TICKER = "^DJI"
BACKTEST_MODEL = "claude-haiku-4-5"  # cheap; fine for a first "is there signal?" read
DIRECTIONAL_BAND = 0.05  # |score| must exceed this to count as a directional call


def _clean(headline):
    """Undo the dataset's Python bytes-literal repr quirk: b\"...\" -> text."""
    if not isinstance(headline, str):
        return ""
    try:
        v = ast.literal_eval(headline)
        return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
    except Exception:
        return headline.strip().strip('"')


def load_days(year, max_days=None):
    """Return {date_str: [headlines]} for the given year (trading days only)."""
    df = pd.read_csv(DATASET)
    df = df[df["Date"].str.startswith(str(year))].sort_values("Date")
    if max_days:
        df = df.head(max_days)

    top_cols = [c for c in df.columns if c.startswith("Top")]
    days = {}
    for _, row in df.iterrows():
        headlines = [_clean(row[c]) for c in top_cols]
        days[row["Date"]] = [h for h in headlines if h]
    return days


def _records_for_day(date_str, headlines):
    """Minimal records the scorer/aggregator understand (all news-tier)."""
    ts = f"{date_str}T12:00:00+00:00"
    return [
        {
            "source": "news-historical",
            "source_tier": 2,          # news → directional weight 1.0
            "title": h,
            "text": h,
            "url": "",
            "timestamp": ts,
            "raw_engagement": 0,
            "run_date": date_str,       # survives scoring (merged through), regroup key
        }
        for h in headlines
    ]


def score_history(days, use_batch, batch_id=None):
    """Score every headline, then aggregate per day → {date: consensus_score}."""
    all_records = [r for d, hs in days.items() for r in _records_for_day(d, hs)]
    print(f"scoring {len(all_records)} headlines across {len(days)} days "
          f"({'batch' if use_batch or batch_id else 'sync'}, {BACKTEST_MODEL}) ...")

    scored = scorer.score(all_records, use_batch=use_batch, model=BACKTEST_MODEL,
                          batch_id=batch_id)

    # regroup by day and aggregate with the production algorithm
    by_day = {}
    for rec in scored:
        by_day.setdefault(rec["run_date"], []).append(rec)

    series = {}
    for date_str, recs in by_day.items():
        now = datetime.fromisoformat(f"{date_str}T23:59:59+00:00")
        series[date_str] = aggregator.aggregate(recs, now=now)["consensus_score"]
    return pd.Series(series).sort_index()


def next_day_returns(year):
    """Next-day index return aligned to each trading day t."""
    px = yf.download(INDEX_TICKER, start=f"{year}-01-01", end=f"{year + 1}-01-15",
                     progress=False, auto_adjust=True)
    close = px["Close"].squeeze()
    ret = close.pct_change().shift(-1)  # return from close_t -> close_{t+1}, indexed at t
    ret.index = ret.index.strftime("%Y-%m-%d")
    return ret


def evaluate(scores, returns):
    """Align scores with next-day returns and compute predictive metrics."""
    df = pd.DataFrame({"score": scores, "ret": returns}).dropna()
    n = len(df)
    if n < 2:
        print("Not enough aligned days to evaluate.")
        return

    # 1) Hit rate on directional calls
    calls = df[df["score"].abs() > DIRECTIONAL_BAND]
    hits = (calls["score"] > 0) == (calls["ret"] > 0)
    hit_rate = hits.mean() if len(calls) else float("nan")
    se = 0.5 / math.sqrt(len(calls)) if len(calls) else float("nan")  # noise band

    # 2) Correlation of score with next-day return
    corr = df["score"].corr(df["ret"])

    # 3) Toy strategy: long when bullish beyond band, else flat (no shorting)
    position = (df["score"] > DIRECTIONAL_BAND).astype(int)
    strat = (1 + position * df["ret"]).prod() - 1
    hold = (1 + df["ret"]).prod() - 1  # buy-and-hold baseline
    up_rate = (df["ret"] > 0).mean()   # base rate of up days

    bar = "=" * 70
    print(f"\n{bar}\nBACKTEST RESULTS\n{bar}")
    print(f"Aligned trading days: {n}")
    print(f"Directional calls (|score|>{DIRECTIONAL_BAND}): {len(calls)}")
    print(f"\nHit rate:          {hit_rate:.1%}   (coinflip 50%, +/- ~{se:.1%} noise)")
    print(f"Base rate up-days: {up_rate:.1%}   (always-long would 'hit' this often)")
    print(f"Correlation:       {corr:+.3f}   (score_t vs next-day return)")
    print(f"\nToy long/flat strategy return: {strat:+.2%}")
    print(f"Buy-and-hold return:           {hold:+.2%}")
    print(bar)

    # Honest verdict
    edge = hit_rate - max(0.5, up_rate) if not math.isnan(hit_rate) else float("nan")
    print("\nRead:")
    if math.isnan(hit_rate) or len(calls) < 20:
        print("  Too few directional calls to conclude anything. Widen the window.")
    elif abs(corr) < 0.05 and abs(edge) < se:
        print("  No detectable edge — consistent with 'general news doesn't predict DJIA'.")
        print("  That's a real (honest) finding, not a bug.")
    elif edge > se:
        print(f"  Possible small edge (~{edge:+.1%} vs baseline). Worth a fidelity pass")
        print("  on FINANCIAL headlines + a longer window before believing it.")
    else:
        print("  Ambiguous / within noise. Longer window needed to tell.")
    print("  Caveats: general (non-financial) news, in-sample, single asset, no costs.")


def main():
    ap = argparse.ArgumentParser(description="Sentiment-signal backtest")
    ap.add_argument("--year", type=int, default=2015)
    ap.add_argument("--max-days", type=int, default=None,
                    help="limit days (for a cheap sync smoke test)")
    ap.add_argument("--batch", action="store_true", help="use Batch API (cheaper)")
    ap.add_argument("--batch-id", default=None,
                    help="resume/collect an already-submitted batch (no re-scoring)")
    args = ap.parse_args()

    days = load_days(args.year, args.max_days)
    scores = score_history(days, use_batch=args.batch, batch_id=args.batch_id)
    returns = next_day_returns(args.year)
    evaluate(scores, returns)


if __name__ == "__main__":
    main()
