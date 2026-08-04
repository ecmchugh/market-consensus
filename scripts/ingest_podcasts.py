#!/usr/bin/env python
"""Ingest new podcast episodes into the corpus.

Forward-only: only episodes not already in `processed_episode` are considered, so
this is safe (and cheap) to run on a schedule. Measured cadence is ~0.5 relevant
episodes/day across the configured shows.

    feeds -> new episodes -> metadata filter -> transcript -> passages
          -> stance scoring (Haiku) -> embeddings -> item store

Everything after "passages" is the SAME path Hacker News items take; podcasts are
just another source. Items carry source_type="podcast" so spoken opinion stays
distinguishable from written opinion for divergence analysis later.

Usage:
    PYTHONPATH=. python scripts/ingest_podcasts.py --dry-run
    PYTHONPATH=. python scripts/ingest_podcasts.py --max-episodes 2
    PYTHONPATH=. python scripts/ingest_podcasts.py --no-whisper   # free transcripts only
    CONSENSUS_DB=corpus.db PYTHONPATH=. python scripts/ingest_podcasts.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

from ingestion.podcasts import DEFAULT_SHOWS, fetch_podcasts
from pipeline import embed
from pipeline.itemstore import get_store
from pipeline.stance import StanceScoringError, score_stance


def load_alias_index() -> tuple[dict, dict]:
    """Build the spoken-alias index from subjects the corpus already knows about.

    Sourced from the resolver's disk cache, so podcast entity matching covers exactly
    the subjects the product covers — no separate hardcoded ticker list to drift.
    """
    from pipeline.transcript import build_alias_index

    path = ".subject_cache.json"
    if not os.path.exists(path):
        print(f"ERROR: {path} not found — resolve some subjects first (scripts/seed_corpus.py)")
        sys.exit(1)
    cache = json.load(open(path))
    resolved: dict[str, dict] = {}
    for v in cache.values():
        if v.get("proxy") and v.get("is_financial"):
            resolved.setdefault(v["proxy"], v)
    return build_alias_index(resolved), {r["proxy"]: r.get("display", r["proxy"]) for r in resolved.values()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-episodes", type=int, default=3, help="transcription budget for this run (default 3)")
    ap.add_argument("--per-show", type=int, default=20, help="how far back to look in each feed")
    ap.add_argument("--shows", type=str, default="", help="comma-separated subset of shows")
    ap.add_argument("--no-whisper", action="store_true", help="only shows that publish transcripts (zero compute)")
    ap.add_argument("--dry-run", action="store_true", help="produce passages but score/store nothing")
    args = ap.parse_args()

    shows = [s.strip() for s in args.shows.split(",") if s.strip()] or DEFAULT_SHOWS
    alias_index, display = load_alias_index()
    store = get_store()
    seen = store.seen_episode_guids()

    print(f"Corpus DB      : {os.getenv('CONSENSUS_DB') or 'corpus.db (default)'}")
    print(f"Subjects known : {len(alias_index)}")
    print(f"Episodes seen  : {len(seen)}")
    print(f"Shows          : {', '.join(shows)}")
    print(f"Budget         : {args.max_episodes} transcription(s) this run"
          f"{' — free transcripts only' if args.no_whisper else ''}\n")

    t0 = time.time()
    records, outcomes = fetch_podcasts(
        alias_index, shows=shows, seen_guids=seen, per_show=args.per_show,
        max_episodes=args.max_episodes, allow_whisper=not args.no_whisper,
    )
    print(f"\n{len(records)} candidate passages from {sum(1 for o in outcomes if o['status']=='ok')} episode(s) "
          f"in {time.time()-t0:.0f}s")

    if args.dry_run:
        print("\n--- DRY RUN: nothing scored or stored ---")
        for r in records[:5]:
            print(f"  [{r['subject']}] {r['text'][:150]}…")
        by = Counter(r["subject"] for r in records)
        print(f"\n  subjects: {dict(by)}")
        return 0

    # --- score, embed, store (identical to the Hacker News path) -----------
    stored_by_ep: Counter = Counter()
    if records:
        by_subject: dict[str, list[dict]] = {}
        for r in records:
            by_subject.setdefault(r["subject"], []).append(r)

        kept: list[dict] = []
        for key, group in by_subject.items():
            name = display.get(key, key)
            try:
                scored = score_stance(group, name, quiet=True)
            except StanceScoringError as e:
                # Loud and fatal: a scoring outage must not be recorded as "this
                # episode had no opinions in it".
                print(f"ERROR: stance scoring failed for {name}: {e}")
                return 1
            print(f"  {key:<9} {len(scored)}/{len(group)} passages carried a genuine view")
            kept.extend(scored)
            for s in scored:
                stored_by_ep[s["external_id"].split(":")[0]] += 1

        if kept:
            print(f"\nembedding {len(kept)} items…")
            vecs = embed.embed_texts([k["text"] for k in kept])
            for k, v in zip(kept, vecs):
                k["embedding"] = v
            n_new = store.upsert_items(kept)
            print(f"stored {n_new} new items (of {len(kept)} scored; rest were duplicates)")

    # Record every episode examined, INCLUDING skips — otherwise each nightly run
    # re-evaluates the same irrelevant back catalogue.
    for o in outcomes:
        store.mark_episode(
            o["guid"], show=o.get("show", ""), title=o.get("title", ""),
            published=o.get("published"), status=o["status"], detail=o.get("detail", ""),
            n_passages=o.get("n_passages", 0), n_items=stored_by_ep.get(o["guid"], 0),
        )

    print(f"\nepisode ledger: {store.episode_stats()}")
    print(f"corpus now: {store.corpus_size()} items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
