"""Pydantic response models for the API.

These type and document the JSON the API returns (and drive the auto-generated
/docs). `from_row` maps a raw Supabase `daily_consensus` row into the response
shape — including tidying the stored JSONB (e.g. top_themes is stored as
[["NVDA", 9], ...] and served as [{"theme": "NVDA", "count": 9}, ...]).
"""

from pydantic import BaseModel


class Theme(BaseModel):
    theme: str
    count: int


class TickerSentiment(BaseModel):
    ticker: str
    score: float
    label: str
    mentions: int
    confidence: str


class ConsensusDay(BaseModel):
    run_date: str
    consensus_score: float
    label: str
    confidence: str
    contested: bool
    dispersion: float
    item_count: int
    contributing_count: int
    tier_means: dict[str, float]
    tickers: list[TickerSentiment]
    top_themes: list[Theme]
    bull_signals: list[str]
    bear_signals: list[str]

    @classmethod
    def from_row(cls, row: dict) -> "ConsensusDay":
        return cls(
            run_date=str(row["run_date"]),
            consensus_score=row["consensus_score"],
            label=row["label"],
            confidence=row["confidence"],
            contested=row["contested"],
            dispersion=row["dispersion"],
            item_count=row["item_count"],
            contributing_count=row["contributing_count"],
            tier_means=row.get("tier_means") or {},
            tickers=[TickerSentiment(**t) for t in (row.get("tickers") or [])],
            top_themes=[Theme(theme=t[0], count=t[1])
                        for t in (row.get("top_themes") or [])],
            bull_signals=row.get("bull_signals") or [],
            bear_signals=row.get("bear_signals") or [],
        )
