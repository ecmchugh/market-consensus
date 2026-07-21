"""Query path — the product. Any market subject → a cited consensus reading.

This is the on-demand half of the architecture (the ingestion half runs once per
item). End to end:

    resolve subject → (fetch live if corpus is thin) → score stance (Haiku, concurrent)
    → embed + store → semantic search the corpus → aggregate → synthesize cited
    report (Sonnet, once) → cache the reading

Cost split (the resume talking point): high-volume per-item stance runs on Haiku
with a prompt-cached rubric; the single expensive synthesis runs on Sonnet once per
query. Readings are cached, so a repeat query is an instant DB read and the cache
doubles as the history the backtest needs.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

from ingestion.sources import fetch_hn
from pipeline import embed, subjects
from pipeline.itemstore import get_store
from pipeline.stance import score_stance

SYNTH_MODEL = "claude-sonnet-5"  # strong model, once per query, for the sourced report

# If a subject has fewer than this many stored items, fetch fresh from the sources
# (hybrid coverage — guarantees an answer for a never-seen subject on day one).
THIN_CORPUS = 25

NEUTRAL_BAND = 15  # |consensus| within this reads as "neutral" rather than bull/bear


def _subject_key(resolved: dict) -> str:
    """Canonical key for a subject: its proxy ticker, else the normalized name.

    Two different phrasings that map to the same instrument (NVDA / "Nvidia") share
    a key, so their items and cached readings collide correctly.
    """
    return (resolved.get("proxy") or resolved["display"]).upper()


def _label(score: float) -> str:
    if score > NEUTRAL_BAND:
        return "bullish"
    if score < -NEUTRAL_BAND:
        return "bearish"
    return "neutral"


def _aggregate(items: list[dict]) -> dict:
    """Turn retrieved, scored items into the headline consensus numbers."""
    scores = [it["score"] for it in items if it.get("score") is not None]
    if not scores:
        return {"consensus_score": 0.0, "conviction": 0.0, "dispersion": 0.0, "volume": 0}
    consensus = sum(scores) / len(scores)
    return {
        "consensus_score": round(consensus, 1),
        "conviction": round(sum(abs(s) for s in scores) / len(scores), 1),  # how strongly held
        "dispersion": round(statistics.pstdev(scores), 1) if len(scores) > 1 else 0.0,
        "volume": len(scores),
    }


def _pick_citations(items: list[dict], n: int = 14) -> list[dict]:
    """Choose a representative, balanced set of items for the report to cite.

    Take the strongest bulls and strongest bears (by |score|) so the synthesis sees
    both sides, not just whatever was most semantically central.
    """
    bulls = sorted((i for i in items if i["score"] > 0), key=lambda i: -i["score"])
    bears = sorted((i for i in items if i["score"] < 0), key=lambda i: i["score"])
    half = n // 2
    picked = bulls[:half] + bears[: n - half]
    # top up from whatever's left if one side was thin
    if len(picked) < n:
        rest = [i for i in items if i not in picked]
        picked += rest[: n - len(picked)]
    return picked[:n]


_SYNTH_SYSTEM = """You are a market-sentiment analyst writing a short, honest consensus brief.

You are given real posts about a subject, each numbered, with a stance score
(-100 = very bearish, +100 = very bullish) and its source. Write ~150 words of
markdown that describes what the crowd actually thinks: the overall lean, the bull
case, the bear case, and any notable disagreement. Cite specific posts inline as
[n] using the given numbers — every substantive claim should carry a citation.

Hard rules:
- You are MEASURING sentiment, not predicting price and not giving advice.
- Ground every claim in the provided posts; never invent facts or numbers.
- Be concise and neutral in tone. If the posts disagree, say so plainly."""


def _synthesize(subject_display: str, agg: dict, citations: list[dict]) -> str:
    """One Sonnet call → a sourced markdown brief citing the numbered posts."""
    import anthropic

    numbered = "\n".join(
        f"[{i+1}] ({c['source']}, stance {c['score']:+d}) {c['text'][:280]}"
        for i, c in enumerate(citations)
    )
    user = (
        f"SUBJECT: {subject_display}\n"
        f"AGGREGATE: consensus {agg['consensus_score']:+} ({_label(agg['consensus_score'])}), "
        f"conviction {agg['conviction']}, dispersion {agg['dispersion']}, {agg['volume']} posts.\n\n"
        f"POSTS:\n{numbered}"
    )
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=SYNTH_MODEL,
        max_tokens=600,
        system=[{"type": "text", "text": _SYNTH_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def run_query(subject_str: str, *, force_refresh: bool = False, max_age_hours: float = 24.0,
              windows: int = 6, per_window: int = 30, limit: int = 0,
              quiet: bool = False) -> dict:
    """Resolve → (fetch if thin) → score → embed/store → search → aggregate →
    synthesize → cache. Returns the reading dict.

    Returns a cached reading immediately if one exists within `max_age_hours`
    (unless force_refresh). Non-market subjects (no proxy) return is_financial=False
    and no report.
    """
    def log(msg):
        if not quiet:
            print(msg)

    resolved = subjects.resolve(subject_str)
    key = _subject_key(resolved)
    store = get_store()

    # 1) Serve fresh cache if we have it.
    if not force_refresh:
        cached = store.get_latest_reading(key)
        if cached and cached.get("computed_at"):
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["computed_at"])).total_seconds() / 3600
            if age_h <= max_age_hours:
                log(f"  cache hit for {key} ({age_h:.1f}h old) — returning instantly")
                cached["cached"] = True
                return cached

    if not resolved.get("is_financial") or not resolved.get("proxy"):
        log(f"  '{subject_str}' has no tradeable proxy — out of scope (markets only).")
        return {"subject": key, "input": subject_str, "is_financial": False,
                "display": resolved["display"], "report_md": None}

    # 2) Hybrid coverage: fetch live if the corpus is thin for this subject.
    have = store.subject_item_count(key) if hasattr(store, "subject_item_count") else 0
    if have < THIN_CORPUS or force_refresh:
        log(f"  corpus has {have} items for {key} → fetching live (HN, {windows}×{per_window})")
        raw = fetch_hn(resolved, period="month", windows=windows, per_window=per_window)
        if limit:
            raw = raw[:limit]
        log(f"  scoring stance on {len(raw)} items (Haiku, concurrent)…")
        scored = score_stance(raw, resolved["display"], quiet=quiet)
        for it in scored:
            it["subject"] = key
        if scored:
            log(f"  embedding + storing {len(scored)} relevant items…")
            vecs = embed.embed_texts([it["text"] for it in scored])
            for it, v in zip(scored, vecs):
                it["embedding"] = v
            store.upsert_items(scored)

    # 3) Retrieve the subject's items from the corpus, ranked by relevance.
    qvec = embed.embed_one(f"{resolved['display']} — {resolved.get('hn_query','')}")
    items = store.semantic_search(qvec, k=400, subject=key)
    if not items:
        log(f"  no relevant items found for {key}.")
        return {"subject": key, "input": subject_str, "display": resolved["display"],
                "is_financial": True, "proxy": resolved["proxy"], "report_md": None, "volume": 0}

    # 4) Aggregate → 5) synthesize a cited report → 6) backtest against the proxy.
    agg = _aggregate(items)
    citations = _pick_citations(items)
    log(f"  synthesizing report (Sonnet) over {len(items)} items…")
    report_md = _synthesize(resolved["display"], agg, citations)

    log(f"  backtesting conviction vs {resolved['proxy']} price…")
    try:
        from analysis.subject_backtest import backtest_subject
        backtest = backtest_subject(items, resolved["proxy"], period="month")
    except Exception as e:  # noqa: BLE001 — a price hiccup shouldn't sink the reading
        log(f"  (backtest skipped: {type(e).__name__})")
        backtest = None

    reading = {
        "subject": key,
        "input": subject_str,
        "display": resolved["display"],
        "proxy": resolved["proxy"],
        "is_financial": True,
        "asset_type": resolved.get("asset_type"),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "label": _label(agg["consensus_score"]),
        **agg,
        "report_md": report_md,
        "citations": [
            {"n": i + 1, "source": c["source"], "url": c.get("url"),
             "score": c["score"], "quote": c["text"][:200]}
            for i, c in enumerate(citations)
        ],
        "backtest": backtest,  # lead/coincident/lag vs the proxy (P6)
        "cached": False,
    }
    store.save_reading(reading)
    return reading


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "Nvidia"
    r = run_query(q)
    print("\n" + "=" * 70)
    print(f"{r['display']}  ({r.get('proxy')})  ·  {r.get('label','?').upper()}  "
          f"consensus {r.get('consensus_score')}  conviction {r.get('conviction')}  "
          f"dispersion {r.get('dispersion')}  n={r.get('volume')}")
    print("=" * 70)
    print(r.get("report_md") or "(no report)")
    if r.get("citations"):
        print("\nReceipts:")
        for c in r["citations"][:6]:
            print(f"  [{c['n']}] {c['source']}  stance {c['score']:+}  {c['url']}")
