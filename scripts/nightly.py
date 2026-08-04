#!/usr/bin/env python
"""Nightly maintenance: keep readings warm, and pull in new podcast episodes.

Two jobs that happen to want the same schedule and the same corpus:

  1. REFRESH. Readings expire after `max_age_hours` (24 by default), so a subject
     seeded yesterday is stale today and its next visitor pays the slow path — ~13s
     to re-synthesize even when the corpus is already deep. Re-running the readings
     off-peak means visitors get the ~10ms cached path instead.

  2. INGEST. Pull new podcast episodes into the corpus. Measured cadence across the
     configured shows is ~0.5 relevant episodes/day, so this is a few minutes of
     work per night, not a batch job.

Order matters: ingest first, then refresh, so the night's new podcast passages are
actually reflected in the readings this run produces.

Bounded by design. `--max-refresh` caps LLM spend per run, and refresh visits the
STALEST subjects first, so an interrupted or budget-limited run still makes the most
valuable progress. Failures on one subject never abort the rest.

    PYTHONPATH=. python scripts/nightly.py --dry-run
    CONSENSUS_DB=corpus.db PYTHONPATH=. python scripts/nightly.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timezone

from pipeline import query
from pipeline.itemstore import get_store
from pipeline.stance import StanceScoringError

DEFAULT_MAX_AGE_H = 24.0


def _age_hours(iso: str | None) -> float:
    if not iso:
        return float("inf")
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600
    except ValueError:
        return float("inf")


def stale_subjects(store, max_age_h: float) -> list[tuple[str, float]]:
    """(subject key, age in hours) for readings older than the TTL, stalest first.

    Derived from what's actually in the store rather than a configured list, so
    anything a user has ever queried keeps itself warm without being registered
    anywhere.
    """
    import sqlite3

    try:
        with store._lock:  # noqa: SLF001 — local backend detail; see fallback below
            rows = store._conn.execute(
                "SELECT subject, MAX(computed_at) FROM subject_reading GROUP BY subject"
            ).fetchall()
    except (AttributeError, sqlite3.Error):
        return []

    out = [(r[0], _age_hours(r[1])) for r in rows]
    return sorted([(s, a) for s, a in out if a > max_age_h], key=lambda x: -x[1])


def run_ingest(args) -> None:
    """Pull new podcast episodes. Never fatal — a bad feed must not stop the refresh."""
    if args.no_ingest:
        print("ingest: skipped (--no-ingest)")
        return
    try:
        from ingestion.podcasts import DEFAULT_SHOWS, fetch_podcasts
        from pipeline.transcript import build_alias_index
    except ImportError as e:
        print(f"ingest: unavailable ({e}) — skipping")
        return

    import json

    from pipeline import embed
    from pipeline.stance import score_stance

    cache_path = os.getenv("SUBJECT_CACHE") or ".subject_cache.json"
    if not os.path.exists(cache_path):
        print(f"ingest: no subject cache at {cache_path} — skipping (nothing to match against)")
        return

    resolved: dict[str, dict] = {}
    for v in json.load(open(cache_path)).values():
        if v.get("proxy") and v.get("is_financial"):
            resolved.setdefault(v["proxy"], v)
    alias_index = build_alias_index(resolved)
    display = {r["proxy"]: r.get("display", r["proxy"]) for r in resolved.values()}

    store = get_store()
    print(f"ingest: {len(alias_index)} subjects known, {len(store.seen_episode_guids())} episodes already seen")

    records, outcomes = fetch_podcasts(
        alias_index, shows=DEFAULT_SHOWS, seen_guids=store.seen_episode_guids(),
        max_episodes=args.max_episodes, allow_whisper=not args.no_whisper, quiet=False,
    )

    stored_by_ep: dict[str, int] = {}
    if records and not args.dry_run:
        by_subject: dict[str, list[dict]] = {}
        for r in records:
            by_subject.setdefault(r["subject"], []).append(r)
        kept: list[dict] = []
        for key, group in by_subject.items():
            try:
                scored = score_stance(group, display.get(key, key), quiet=True)
            except StanceScoringError as e:
                # A scoring outage must be loud, and must not be recorded as
                # "these episodes contained no opinions".
                print(f"ingest: ABORT — stance scoring failed: {e}")
                return
            kept.extend(scored)
            for s in scored:
                ep = s["external_id"].split(":")[0]
                stored_by_ep[ep] = stored_by_ep.get(ep, 0) + 1
        if kept:
            vecs = embed.embed_texts([k["text"] for k in kept])
            for k, v in zip(kept, vecs):
                k["embedding"] = v
            print(f"ingest: stored {store.upsert_items(kept)} new items from {len(records)} passages")

    if not args.dry_run:
        for o in outcomes:
            store.mark_episode(
                o["guid"], show=o.get("show", ""), title=o.get("title", ""),
                published=o.get("published"), status=o["status"], detail=o.get("detail", ""),
                n_passages=o.get("n_passages", 0), n_items=stored_by_ep.get(o["guid"], 0),
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_H)
    ap.add_argument("--max-refresh", type=int, default=40, help="cap on readings recomputed per run")
    ap.add_argument("--max-episodes", type=int, default=3, help="cap on episodes transcribed per run")
    ap.add_argument("--no-ingest", action="store_true", help="refresh only")
    ap.add_argument("--no-refresh", action="store_true", help="ingest only")
    ap.add_argument("--no-whisper", action="store_true", help="only shows publishing transcripts")
    ap.add_argument("--dry-run", action="store_true", help="report what would happen, change nothing")
    args = ap.parse_args()

    started = time.time()
    store = get_store()
    print(f"nightly: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print(f"corpus : {store.corpus_size()} items, db={os.getenv('CONSENSUS_DB') or 'corpus.db'}\n")

    # 1) Ingest BEFORE refresh, so tonight's new passages land in tonight's readings.
    run_ingest(args)

    # 2) Refresh stale readings.
    if args.no_refresh:
        print("\nrefresh: skipped (--no-refresh)")
    else:
        stale = stale_subjects(store, args.max_age_hours)
        print(f"\nrefresh: {len(stale)} reading(s) older than {args.max_age_hours:g}h"
              f"{f', doing the {args.max_refresh} stalest' if len(stale) > args.max_refresh else ''}")
        if args.dry_run:
            for s, age in stale[:args.max_refresh]:
                print(f"  would refresh {s:<10} ({age:.0f}h old)")
        else:
            done = failed = 0
            for s, age in stale[:args.max_refresh]:
                t0 = time.time()
                try:
                    query.run_query(s, force_refresh=True, quiet=True)
                    done += 1
                    print(f"  {s:<10} refreshed ({age:.0f}h old) in {time.time()-t0:.0f}s")
                except StanceScoringError as e:
                    # Fatal for the whole run: if scoring is down, every remaining
                    # subject will fail the same way and burn time proving it.
                    print(f"  {s:<10} ABORT — scoring unavailable: {e}")
                    return 1
                except Exception as e:  # noqa: BLE001 — one bad subject shouldn't end the run
                    failed += 1
                    print(f"  {s:<10} FAILED {type(e).__name__}: {e}")
                    traceback.print_exc(limit=1)
            print(f"\nrefresh: {done} refreshed, {failed} failed")

    print(f"\nnightly: done in {time.time()-started:.0f}s — corpus {store.corpus_size()} items")
    if not args.dry_run:
        print(f"episodes: {store.episode_stats()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
