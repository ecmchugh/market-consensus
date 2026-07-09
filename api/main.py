"""Market Consensus API — read-only HTTP layer over the daily consensus data.

Serves what the pipeline stored in Supabase (`daily_consensus`) so the React
dashboard can consume it. Read-only: the daily pipeline does the writing; this
just serves. Endpoints are added incrementally (see the routes below).

Run locally:
    uvicorn api.main:app --reload
    -> interactive docs at http://localhost:8000/docs
"""

from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api import models
from pipeline import store

app = FastAPI(
    title="Market Consensus API",
    description="Daily market-sentiment consensus, served from stored pipeline output.",
    version="0.1.0",
)

# The dashboard runs on a different origin (Vercel/localhost), so allow browser
# calls. Read-only public data, so permissive origins are fine for now; tighten
# to the deployed frontend origin in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Liveness check."""
    return {"status": "ok"}


@app.get("/consensus/latest", response_model=models.ConsensusDay)
def consensus_latest():
    """The most recent day's full consensus."""
    row = store.get_latest()
    if row is None:
        raise HTTPException(status_code=404, detail="No consensus data yet")
    return models.ConsensusDay.from_row(row)


@app.get("/consensus/history", response_model=list[models.HistoryPoint])
def consensus_history(days: int = Query(30, ge=1, le=365)):
    """Daily consensus scores over time (oldest first) — for the trend chart."""
    rows = store.get_history(days)
    return [models.HistoryPoint.from_row(r) for r in rows]


# Declared after /latest and /history so those literal paths win over this
# path param. `date` typing auto-rejects malformed dates with a 422.
@app.get("/consensus/{run_date}", response_model=models.ConsensusDay)
def consensus_by_date(run_date: date):
    """One specific day's full consensus."""
    row = store.get_by_date(run_date)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No consensus for {run_date}")
    return models.ConsensusDay.from_row(row)
