#!/usr/bin/env python
"""Seed the corpus with a set of subjects — and measure source coverage while doing it.

Two jobs in one pass:

  1. **Prime the cache.** A cold read is ~40s and costs money; a cached one is ~8ms
     and free. Seeding means a visitor's first click is usually instant instead of
     a 40-second wait on a spinner.

  2. **Measure coverage.** The subject list deliberately includes names OUTSIDE
     Hacker News's wheelhouse (energy, banks, pharma, retail) alongside the tech and
     crypto names it covers well. The per-subject item counts printed at the end
     quantify how thin single-source coverage actually is — which is the evidence
     for whether a second source (or podcast ingestion) is worth building.

Runs the pipeline DIRECTLY rather than through the API, so the per-IP rate limit and
daily spend budget in api/limits.py don't apply — those exist to stop strangers, not
the operator. Cost is real: roughly one Haiku call per fetched item plus one Sonnet
synthesis per subject.

Usage:
    PYTHONPATH=. python scripts/seed_corpus.py --dry-run      # list subjects + cost estimate
    PYTHONPATH=. python scripts/seed_corpus.py                # seed everything
    PYTHONPATH=. python scripts/seed_corpus.py --only Nvidia,Bitcoin
    CONSENSUS_DB=corpus.db PYTHONPATH=. python scripts/seed_corpus.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

# Subjects to seed. `core` = expected to be well covered by Hacker News;
# `probe` = deliberately outside HN's wheelhouse, included to MEASURE the gap
# rather than to pad the corpus. Don't drop the probes because they come back
# thin — a thin probe is the result, not a failure.
CORE = [
    "Nvidia", "AMD", "Intel", "Broadcom", "TSMC", "Micron", "Arm",
    "Apple", "Microsoft", "Google", "Meta", "Amazon", "Tesla",
    "Oracle", "Palantir", "Netflix", "Salesforce", "Snowflake", "Coinbase",
    "Bitcoin", "Ethereum",
    "Semiconductors", "AI infrastructure", "Cloud computing",
    "Quantum computing", "Cybersecurity",
]
PROBE = ["Exxon Mobil", "JPMorgan", "Pfizer", "Walmart", "Uranium", "Solana"]

# Coverage buckets for the summary table (item counts after stance filtering).
RICH, OK_, THIN = 40, 15, 1


def bucket(n: int) -> str:
    if n >= RICH:
        return "rich"
    if n >= OK_:
        return "ok"
    if n >= THIN:
        return "thin"
    return "empty"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--windows", type=int, default=12,
                    help="months of history to fetch per subject (default 12 — deeper than the "
                         "query-path default of 6 so the backtest has enough periods to be meaningful)")
    ap.add_argument("--per-window", type=int, default=25, help="items fetched per month (default 25)")
    ap.add_argument("--only", type=str, default="", help="comma-separated subset of subjects")
    ap.add_argument("--force", action="store_true", help="recompute even if a fresh reading is cached")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and cost estimate, spend nothing")
    ap.add_argument("--out", type=str, default="", help="write the coverage report as JSON here")
    args = ap.parse_args()

    subjects = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else CORE + PROBE
    probes = set(PROBE)

    max_items = args.windows * args.per_window
    # Haiku stance cost measured at ~$0.49-0.69 per 1k items (docs/BUILD_PLAN.md),
    # plus one Sonnet synthesis per subject (~$0.02). Fetches usually return fewer
    # than the ceiling, so this is an upper bound.
    hi = len(subjects) * (max_items / 1000 * 0.69 + 0.03)
    lo = len(subjects) * (max_items / 1000 * 0.49 + 0.02) * 0.5

    print(f"Corpus DB    : {os.getenv('CONSENSUS_DB') or 'corpus.db (default)'}")
    print(f"Subjects     : {len(subjects)}  ({len(CORE)} core + {len(PROBE)} coverage probes)")
    print(f"Fetch depth  : {args.windows} months x {args.per_window}/mo = up to {max_items} items each")
    print(f"Cost estimate: ~${lo:.2f}-{hi:.2f} total (upper bound; most subjects fetch fewer)")
    print(f"Time estimate: ~{len(subjects) * 90 / 60:.0f} min\n")

    if args.dry_run:
        for s in subjects:
            print(f"  {'probe' if s in probes else 'core '}  {s}")
        return 0

    from pipeline import query  # imported late so --dry-run needs no model deps

    results, started = [], time.time()
    for i, subj in enumerate(subjects, 1):
        t0 = time.time()
        print(f"[{i}/{len(subjects)}] {subj} …", flush=True)
        try:
            r = query.run_query(subj, force_refresh=args.force, windows=args.windows,
                                per_window=args.per_window, quiet=True)
            vol = int(r.get("volume") or 0)
            bt = r.get("backtest") or {}
            row = {
                "subject": subj,
                "kind": "probe" if subj in probes else "core",
                "key": r.get("subject"),
                "proxy": r.get("proxy"),
                "is_financial": bool(r.get("is_financial")),
                "volume": vol,
                "coverage": bucket(vol),
                "consensus": r.get("consensus_score"),
                "backtest_periods": bt.get("n_periods"),
                "cached": bool(r.get("cached")),
                "seconds": round(time.time() - t0, 1),
            }
            print(f"      → {vol} items ({row['coverage']}), proxy {row['proxy']}, {row['seconds']}s", flush=True)
        except Exception as e:  # noqa: BLE001 — one bad subject must not end the run
            row = {"subject": subj, "kind": "probe" if subj in probes else "core",
                   "error": f"{type(e).__name__}: {e}", "volume": 0, "coverage": "error",
                   "seconds": round(time.time() - t0, 1)}
            print(f"      ! FAILED {row['error']}", flush=True)
            traceback.print_exc(limit=2)
        results.append(row)

    # --- coverage report ---------------------------------------------------
    print(f"\n{'=' * 62}\nCOVERAGE REPORT  ({time.time() - started:.0f}s total)\n{'=' * 62}")
    print(f"{'subject':<22}{'kind':<8}{'items':>7}  {'coverage':<9}{'proxy'}")
    for r in sorted(results, key=lambda r: -r.get("volume", 0)):
        print(f"{r['subject']:<22}{r['kind']:<8}{r.get('volume', 0):>7}  "
              f"{r.get('coverage', '?'):<9}{r.get('proxy') or r.get('error', '')}")

    for kind in ("core", "probe"):
        rows = [r for r in results if r["kind"] == kind]
        if not rows:
            continue
        vols = [r.get("volume", 0) for r in rows]
        counts = {b: sum(1 for r in rows if r.get("coverage") == b) for b in ("rich", "ok", "thin", "empty", "error")}
        print(f"\n{kind.upper():<6} n={len(rows)}  median items={sorted(vols)[len(vols) // 2]}  " +
              "  ".join(f"{k}={v}" for k, v in counts.items() if v))

    if args.out:
        with open(args.out, "w") as fh:
            json.dump(results, fh, indent=2)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
