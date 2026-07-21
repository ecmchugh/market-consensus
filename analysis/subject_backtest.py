"""Subject backtest — the honest credibility panel behind every reading.

Bounding the product to MARKETS buys us one thing nothing else can fake: a
ground-truth answer key. For any subject we build a per-period conviction series
from the stored items and align it to the proxy's price returns, then report
whether the crowd's mood LED, moved WITH, or LAGGED the price.

This is deliberately honest — with few periods the correlation is reported with n
and flagged as thin, not dressed up. "Measured against ground truth, mostly noise"
is the point: it's the claim a general 'any topic' sentiment tool can never make.

Reuses the same period-bucketing (`pipeline.aggregate`) and price fetch the Slice-2
backtest used, so the number here is consistent with that analysis.
"""

from __future__ import annotations

import numpy as np

from pipeline.aggregate import aggregate_by_period


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson r, or None if too few points / no variance (report honestly)."""
    if len(xs) < 3 or len(ys) < 3:
        return None
    x, y = np.asarray(xs, float), np.asarray(ys, float)
    if x.std() == 0 or y.std() == 0:
        return None
    return round(float(np.corrcoef(x, y)[0, 1]), 3)


def backtest_subject(items: list[dict], proxy: str, period: str = "month") -> dict:
    """Align conviction to proxy returns; return lead/coincident/lag correlations.

    - conviction[t] : the aggregated mood in period t.
    - return[t]     : proxy price return over period t.
    - lead          : conviction[t] vs return[t+1]  (did mood precede the move?)
    - coincident    : conviction[t] vs return[t]    (did they move together?)
    - lag           : conviction[t] vs return[t-1]  (did the move drive mood?)
    """
    from slice1_prove_loop import fetch_price  # price fetch lives with the orchestrator

    readings = aggregate_by_period(items, period, min_items=1)
    if len(readings) < 3:
        return {"period": period, "n_periods": len(readings),
                "note": "too few periods to backtest (need >= 3)",
                "lead_r": None, "coincident_r": None, "lag_r": None, "series": []}

    conv = {r["period"]: r["consensus"] for r in readings}
    periods = sorted(conv)
    start, end = periods[0] + "-01", periods[-1] + "-28"
    prices = {p["period"]: p["close"] for p in fetch_price(proxy, start, end, period)}

    # Build the aligned series: for each period we need its return (needs prev close).
    ordered = sorted(prices)
    ret = {}
    for i in range(1, len(ordered)):
        prev, cur = ordered[i - 1], ordered[i]
        if prices[prev]:
            ret[cur] = (prices[cur] - prices[prev]) / prices[prev]

    series = []
    for p in periods:
        series.append({"period": p, "conviction": conv[p],
                       "price": prices.get(p), "return": round(ret[p], 4) if p in ret else None})

    # Pair up conviction[t] with return at t (coincident), t+1 (lead), t-1 (lag).
    def paired(shift: int):
        xs, ys = [], []
        for i, p in enumerate(periods):
            j = i + shift
            if 0 <= j < len(periods):
                tgt = periods[j]
                if p in conv and tgt in ret:
                    xs.append(conv[p]); ys.append(ret[tgt])
        return xs, ys

    lead_x, lead_y = paired(+1)
    coin_x, coin_y = paired(0)
    lag_x, lag_y = paired(-1)

    return {
        "period": period,
        "n_periods": len(periods),
        "proxy": proxy,
        "lead_r": _pearson(lead_x, lead_y),
        "coincident_r": _pearson(coin_x, coin_y),
        "lag_r": _pearson(lag_x, lag_y),
        "n_pairs": {"lead": len(lead_x), "coincident": len(coin_x), "lag": len(lag_x)},
        "series": series,
        "note": ("thin — interpret with caution" if len(periods) < 6
                 else "did the informed crowd's mood lead, track, or lag the price?"),
    }
