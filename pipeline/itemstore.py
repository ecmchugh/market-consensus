"""Item store — the RAG corpus + cached readings, behind a swappable interface.

Two things live here:
  * `item`            — every scored, embedded opinion (the searchable corpus).
  * `subject_reading` — a computed consensus for a subject at a point in time
                        (cached → doubles as the history the backtest runs on).

`ItemStore` is the interface the query path talks to. `LocalItemStore` implements
it on SQLite + numpy cosine similarity so the whole engine runs with zero external
infra (useful while the Supabase project is down, and for tests/CI). A
`SupabaseItemStore` implementing the SAME interface over Postgres + pgvector is the
production backend — see `db/pgvector_schema.sql` for its migration. Callers use
`get_store()` and never care which backend answers.

Vectors are 384-dim (see pipeline/embed.py). In SQLite they're stored as raw
float32 bytes; pgvector stores them natively as `vector(384)`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

DEFAULT_DB_PATH = Path("corpus.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ItemStore:
    """Interface both backends implement (documents the contract)."""

    def upsert_items(self, items: list[dict]) -> int:  # pragma: no cover - interface
        """Insert new items (dedup by external_id); return count newly inserted."""
        raise NotImplementedError

    def semantic_search(self, query_vec: list[float], k: int = 200,
                        subject: str | None = None) -> list[dict]:  # pragma: no cover
        """Return up to k items most cosine-similar to query_vec (with stance scores)."""
        raise NotImplementedError

    def corpus_size(self) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def save_reading(self, reading: dict) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def get_latest_reading(self, subject: str) -> dict | None:  # pragma: no cover
        raise NotImplementedError

    def get_reading_history(self, subject: str, limit: int = 90) -> list[dict]:  # pragma: no cover
        raise NotImplementedError


class LocalItemStore(ItemStore):
    """SQLite + in-process numpy cosine. No external services required."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = str(db_path)
        # check_same_thread=False: FastAPI serves sync endpoints from a threadpool,
        # so the connection is touched from multiple threads. A lock serializes all
        # access to keep that safe (sqlite writes aren't concurrent anyway).
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS item (
                external_id  TEXT PRIMARY KEY,   -- url / source id; dedup key
                source       TEXT,
                source_type  TEXT,               -- informed | crowd
                subject      TEXT,               -- the subject this was fetched for
                title        TEXT,
                text         TEXT,
                author       TEXT,
                url          TEXT,
                timestamp    TEXT,               -- ISO-8601
                score        INTEGER,            -- stance -100..+100
                rationale    TEXT,
                embedding    BLOB,               -- float32[384]
                created_at   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_item_subject ON item(subject);

            CREATE TABLE IF NOT EXISTS subject_reading (
                subject         TEXT,
                computed_at     TEXT,
                label           TEXT,            -- bullish | neutral | bearish
                consensus_score REAL,
                conviction      REAL,
                dispersion      REAL,
                volume          INTEGER,
                proxy           TEXT,
                is_financial    INTEGER,
                report_md       TEXT,
                citations       TEXT,            -- json
                backtest        TEXT,            -- json (null until computed)
                PRIMARY KEY (subject, computed_at)
            );
            """
        )
        # Lightweight migration: add columns introduced after a db was first created.
        for col, decl in [("label", "TEXT")]:
            try:
                self._conn.execute(f"ALTER TABLE subject_reading ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass  # column already exists
        self._conn.commit()

    # --- corpus writes/reads ------------------------------------------------
    # All DB access holds self._lock so the single connection is safe under
    # FastAPI's threadpool (see __init__).
    def upsert_items(self, items: list[dict]) -> int:
        with self._lock:
            inserted = 0
            for it in items:
                emb = it.get("embedding")
                blob = np.asarray(emb, dtype=np.float32).tobytes() if emb is not None else None
                cur = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO item
                        (external_id, source, source_type, subject, title, text, author,
                         url, timestamp, score, rationale, embedding, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        it.get("url") or it.get("external_id"),
                        it.get("source"),
                        it.get("source_type"),
                        it.get("subject"),
                        it.get("title"),
                        it.get("text"),
                        (it.get("metadata") or {}).get("author"),
                        it.get("url"),
                        it.get("timestamp"),
                        it.get("score"),
                        it.get("rationale"),
                        blob,
                        _now_iso(),
                    ),
                )
                inserted += cur.rowcount
            self._conn.commit()
            return inserted

    def semantic_search(self, query_vec: list[float], k: int = 200,
                        subject: str | None = None) -> list[dict]:
        where, params = "WHERE embedding IS NOT NULL", []
        if subject is not None:
            where += " AND subject = ?"
            params.append(subject)
        with self._lock:
            rows = self._conn.execute(f"SELECT * FROM item {where}", params).fetchall()
        if not rows:
            return []

        mat = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
        q = np.asarray(query_vec, dtype=np.float32)
        # Cosine similarity: normalize both sides, then dot.
        mat_n = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
        q_n = q / (np.linalg.norm(q) + 1e-9)
        sims = mat_n @ q_n

        order = np.argsort(-sims)[:k]
        out = []
        for i in order:
            d = dict(rows[i])
            d.pop("embedding", None)
            d["similarity"] = float(sims[i])
            out.append(d)
        return out

    def corpus_size(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]

    def subject_item_count(self, subject: str) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM item WHERE subject = ?", (subject,)
            ).fetchone()[0]

    # --- cached readings ----------------------------------------------------
    def save_reading(self, reading: dict) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO subject_reading
                    (subject, computed_at, label, consensus_score, conviction, dispersion,
                     volume, proxy, is_financial, report_md, citations, backtest)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    reading["subject"],
                    reading.get("computed_at") or _now_iso(),
                    reading.get("label"),
                    reading.get("consensus_score"),
                    reading.get("conviction"),
                    reading.get("dispersion"),
                    reading.get("volume"),
                    reading.get("proxy"),
                    int(bool(reading.get("is_financial"))),
                    reading.get("report_md"),
                    json.dumps(reading.get("citations") or []),
                    json.dumps(reading["backtest"]) if reading.get("backtest") is not None else None,
                ),
            )
            self._conn.commit()

    def _reading_row_to_dict(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        d["is_financial"] = bool(d.get("is_financial"))
        d["citations"] = json.loads(d["citations"]) if d.get("citations") else []
        d["backtest"] = json.loads(d["backtest"]) if d.get("backtest") else None
        return d

    def get_latest_reading(self, subject: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM subject_reading WHERE subject = ? ORDER BY computed_at DESC LIMIT 1",
                (subject,),
            ).fetchone()
        return self._reading_row_to_dict(r) if r else None

    def get_reading_history(self, subject: str, limit: int = 90) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM subject_reading WHERE subject = ? ORDER BY computed_at ASC LIMIT ?",
                (subject, limit),
            ).fetchall()
        return [self._reading_row_to_dict(r) for r in rows]


class SupabaseItemStore(ItemStore):
    """Postgres + pgvector backend (production) — same interface as LocalItemStore.

    Talks to the schema in db/pgvector_schema.sql: `item` with a `vector(384)`
    column, `subject_reading`, and the `match_items(query_embedding, match_count,
    filter_subject)` cosine-search function. Requires SUPABASE_URL / SUPABASE_KEY.

    NOTE: written to the same contract the local backend was verified against, but
    NOT yet run end-to-end — the Supabase project is currently unreachable (DNS
    does not resolve). To activate: restore the project, run the migration, then
    `CONSENSUS_BACKEND=supabase`. Verify against the live project before trusting.
    """

    def __init__(self):
        # Reuse pipeline.store's client factory (loads .env, validates creds).
        from pipeline import store as _store
        self._client = _store._client()

    @staticmethod
    def _vec(embedding) -> str:
        """pgvector's text form: '[0.1,0.2,...]' — how PostgREST casts to vector()."""
        return "[" + ",".join(f"{float(x):.6f}" for x in embedding) + "]"

    def upsert_items(self, items: list[dict]) -> int:
        rows = [
            {
                "external_id": it.get("url") or it.get("external_id"),
                "source": it.get("source"),
                "source_type": it.get("source_type"),
                "subject": it.get("subject"),
                "title": it.get("title"),
                "text": it.get("text"),
                "author": (it.get("metadata") or {}).get("author"),
                "url": it.get("url"),
                "timestamp": it.get("timestamp"),
                "score": it.get("score"),
                "rationale": it.get("rationale"),
                "embedding": self._vec(it["embedding"]) if it.get("embedding") is not None else None,
            }
            for it in items
        ]
        if not rows:
            return 0
        # ignoreDuplicates → keep the first write for a given external_id (dedup).
        self._client.table("item").upsert(
            rows, on_conflict="external_id", ignore_duplicates=True
        ).execute()
        return len(rows)  # PostgREST doesn't report inserted-vs-ignored; caller treats as best-effort

    def semantic_search(self, query_vec: list[float], k: int = 200,
                        subject: str | None = None) -> list[dict]:
        resp = self._client.rpc(
            "match_items",
            {"query_embedding": self._vec(query_vec), "match_count": k, "filter_subject": subject},
        ).execute()
        out = []
        for row in resp.data or []:
            row.pop("embedding", None)
            out.append(row)
        return out

    def corpus_size(self) -> int:
        resp = self._client.table("item").select("external_id", count="exact").limit(0).execute()
        return resp.count or 0

    def subject_item_count(self, subject: str) -> int:
        resp = (self._client.table("item").select("external_id", count="exact")
                .eq("subject", subject).limit(0).execute())
        return resp.count or 0

    def save_reading(self, reading: dict) -> None:
        row = {k: reading.get(k) for k in (
            "subject", "computed_at", "label", "consensus_score", "conviction",
            "dispersion", "volume", "proxy", "is_financial", "report_md",
            "citations", "backtest")}
        row["computed_at"] = row.get("computed_at") or _now_iso()
        # citations/backtest are jsonb — the client serializes dict/list natively.
        self._client.table("subject_reading").upsert(
            row, on_conflict="subject,computed_at"
        ).execute()

    def get_latest_reading(self, subject: str) -> dict | None:
        resp = (self._client.table("subject_reading").select("*")
                .eq("subject", subject).order("computed_at", desc=True).limit(1).execute())
        return resp.data[0] if resp.data else None

    def get_reading_history(self, subject: str, limit: int = 90) -> list[dict]:
        resp = (self._client.table("subject_reading").select("*")
                .eq("subject", subject).order("computed_at", desc=False).limit(limit).execute())
        return resp.data or []


_STORE: ItemStore | None = None


def get_store() -> ItemStore:
    """Return the process-wide store. Defaults to local SQLite; set
    CONSENSUS_BACKEND=supabase (with a restored project + db/pgvector_schema.sql
    applied) to use the Postgres/pgvector backend."""
    import os

    global _STORE
    if _STORE is None:
        if os.getenv("CONSENSUS_BACKEND", "local").lower() == "supabase":
            _STORE = SupabaseItemStore()
        else:
            _STORE = LocalItemStore()
    return _STORE
