"""Market Consensus API — HTTP layer over the subject consensus engine.

The one write-capable endpoint is `POST /subjects/query`: it runs (or returns a
cached) reading for any market subject. Everything else is a fast read over stored
readings + corpus. Readings are computed by `pipeline.query` and cached in the item
store, so a repeat query is an instant DB read.

Run locally:
    uvicorn api.main:app --reload
    -> interactive docs at http://localhost:8000/docs
"""

import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api import limits
from api.models import Backtest, CorpusStats, Health, Reading
from pipeline import query, subjects
from pipeline.itemstore import get_store

app = FastAPI(
    title="Market Consensus API",
    description="Crowd-conviction readings for any market subject, with a price backtest.",
    version="0.2.0",
)

# Origins allowed to call this API, comma-separated in ALLOWED_ORIGINS. Defaults to
# the local dev servers, so an unconfigured deploy is closed rather than open —
# forgetting the env var breaks the frontend loudly instead of silently exposing
# the paid endpoint to every origin on the internet.
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _key(subject: str) -> str:
    """Resolve a free-text subject to its canonical store key (the proxy ticker)."""
    return query._subject_key(subjects.resolve(subject))


class QueryRequest(BaseModel):
    subject: str
    force_refresh: bool = False


@app.get("/health", response_model=Health)
def health():
    return {"status": "ok"}


@app.get("/corpus/stats", response_model=CorpusStats)
def corpus_stats():
    """Corpus size — useful as a liveness/coverage metric."""
    return {"items": get_store().corpus_size()}


@app.post("/subjects/query", response_model=Reading, dependencies=[Depends(limits.enforce_rate_limit)])
def subjects_query(req: QueryRequest):
    """Run (or return cached) consensus reading for a subject. The one heavy path.

    Guarded two ways (see api/limits.py): a per-IP rate limit runs as a dependency
    BEFORE this body — so subject resolution, itself an LLM call, is also covered —
    and a global daily budget caps total cold runs. The budget is checked only when
    the request would actually be a cold run; serving an existing cached reading
    costs nothing and so is never refused for budget reasons.
    """
    if not req.force_refresh:
        cached = query.get_fresh_cached(req.subject)
        if cached is not None:
            return cached

    limits.enforce_daily_budget(get_store())
    reading = query.run_query(req.subject, force_refresh=req.force_refresh, quiet=True)
    if not reading.get("is_financial"):
        raise HTTPException(
            status_code=422,
            detail=f"'{req.subject}' has no tradeable proxy — this product covers market subjects only.",
        )
    return reading


@app.get("/subjects/{subject}/latest", response_model=Reading)
def subject_latest(subject: str):
    """Most recent cached reading for a subject (404 if never queried)."""
    reading = get_store().get_latest_reading(_key(subject))
    if reading is None:
        raise HTTPException(status_code=404, detail=f"No reading yet for '{subject}' — POST /subjects/query first.")
    return reading


@app.get("/subjects/{subject}/history", response_model=list[Reading])
def subject_history(subject: str, limit: int = 90):
    """Reading trend over time (oldest first) — for the conviction chart."""
    return get_store().get_reading_history(_key(subject), limit=limit)


@app.get("/subjects/{subject}/backtest", response_model=Backtest)
def subject_backtest(subject: str):
    """The lead/coincident/lag panel from the latest reading (404 if none)."""
    reading = get_store().get_latest_reading(_key(subject))
    if reading is None:
        raise HTTPException(status_code=404, detail=f"No reading yet for '{subject}' — POST /subjects/query first.")
    return reading.get("backtest") or {"note": "no backtest available for this reading"}
