"""Market Consensus API — HTTP layer over the subject consensus engine.

The one write-capable endpoint is `POST /subjects/query`: it runs (or returns a
cached) reading for any market subject. Everything else is a fast read over stored
readings + corpus. Readings are computed by `pipeline.query` and cached in the item
store, so a repeat query is an instant DB read.

Run locally:
    uvicorn api.main:app --reload
    -> interactive docs at http://localhost:8000/docs
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.models import Backtest, CorpusStats, Health, Reading
from pipeline import query, subjects
from pipeline.itemstore import get_store

app = FastAPI(
    title="Market Consensus API",
    description="Crowd-conviction readings for any market subject, with a price backtest.",
    version="0.2.0",
)

# The dashboard runs on a different origin (Vercel/localhost). Read-mostly public
# data, so permissive origins are fine for now; tighten to the deployed frontend
# origin in production. POST is allowed for /subjects/query.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.post("/subjects/query", response_model=Reading)
def subjects_query(req: QueryRequest):
    """Run (or return cached) consensus reading for a subject. The one heavy path."""
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
