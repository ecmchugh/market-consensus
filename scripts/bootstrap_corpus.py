#!/usr/bin/env python
"""Put a corpus on the persistent volume before the API starts.

The deploy problem this solves: `corpus.db` is gitignored (it's regenerable data,
not source), so a Railway build has no corpus in it. A freshly deployed instance
would come up empty, and every visitor's first click would pay the ~40s cold path —
on a subject nobody has seeded, that's the worst possible first impression.

So a snapshot is baked into the image at `SEED_PATH`, and on boot we copy it to the
volume IF AND ONLY IF the volume has no corpus yet. That means:
  * first deploy  → instantly populated with the seeded subjects
  * later deploys → the volume's corpus (with everything users have since queried)
                    is left completely alone; the seed is never re-applied

Idempotent and safe to run on every container start. Never overwrites live data.

Env:
  CONSENSUS_DB   destination (Railway: /data/corpus.db). Required in production.
  CORPUS_SEED    override the baked seed path (default: seed/corpus.seed.db)
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

SEED_PATH = Path(os.getenv("CORPUS_SEED") or "seed/corpus.seed.db")


def _describe(db: Path) -> str:
    """Item/reading counts, so the boot log says what corpus we're actually serving."""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        items = con.execute("SELECT COUNT(*) FROM item").fetchone()[0]
        reads = con.execute("SELECT COUNT(*) FROM subject_reading").fetchone()[0]
        con.close()
        return f"{items} items, {reads} readings"
    except sqlite3.Error as e:
        return f"unreadable ({e})"


def main() -> int:
    dest_raw = os.getenv("CONSENSUS_DB")
    if not dest_raw:
        print("bootstrap: CONSENSUS_DB unset — using the app default, nothing to do")
        return 0

    dest = Path(dest_raw)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and dest.stat().st_size > 0:
        print(f"bootstrap: {dest} already present ({_describe(dest)}) — leaving it alone")
        return 0

    if not SEED_PATH.exists():
        # Not fatal: an empty corpus still serves, it just starts cold. Say so loudly
        # rather than letting an empty site look like a data-loss bug.
        print(f"bootstrap: WARNING no seed at {SEED_PATH} — starting with an EMPTY corpus. "
              f"Every first query will run the slow cold path.")
        return 0

    # Copy to a temp name and rename, so a crash mid-copy can't leave a truncated
    # database that the next boot would mistake for a real one.
    tmp = dest.with_suffix(dest.suffix + ".partial")
    print(f"bootstrap: seeding {dest} from {SEED_PATH} ({_describe(SEED_PATH)})…")
    shutil.copyfile(SEED_PATH, tmp)
    os.replace(tmp, dest)
    print(f"bootstrap: done — serving {_describe(dest)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
