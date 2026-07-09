"""Market Consensus API — read-only HTTP layer over the daily consensus data.

Serves what the pipeline stored in Supabase (`daily_consensus`) so the React
dashboard can consume it. Read-only: the daily pipeline does the writing; this
just serves. Endpoints are added incrementally (see the routes below).

Run locally:
    uvicorn api.main:app --reload
    -> interactive docs at http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
