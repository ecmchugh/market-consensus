"""Pydantic response models for the API.

These type and document the JSON the API returns and drive the auto-generated
OpenAPI/Swagger docs. They mirror the dicts produced by `pipeline.query` and
`pipeline.itemstore`; FastAPI validates/coerces the returned dicts against them,
dropping internal keys and filling optionals for cached-from-store readings that
carry fewer fields than a freshly computed one.
"""

from __future__ import annotations

from pydantic import BaseModel


class Citation(BaseModel):
    """One receipt behind the report — a real post the synthesis cited as [n]."""

    n: int
    source: str
    url: str | None = None
    score: int
    quote: str


class Backtest(BaseModel):
    """Lead/coincident/lag of conviction vs. the proxy's forward returns.

    Correlations are null when there are too few periods to compute honestly
    (see `note`). `series` is passed through untyped so the raw per-period
    {period, conviction, price, return} objects reach the client unchanged.
    """

    period: str | None = None
    n_periods: int | None = None
    proxy: str | None = None
    lead_r: float | None = None
    coincident_r: float | None = None
    lag_r: float | None = None
    n_pairs: dict[str, int] | None = None
    series: list[dict] = []
    note: str | None = None


class Reading(BaseModel):
    """A consensus reading for a subject. Fields optional so a cached row (which
    stores fewer fields than a freshly computed reading) validates cleanly."""

    subject: str
    display: str | None = None
    input: str | None = None
    proxy: str | None = None
    asset_type: str | None = None
    is_financial: bool
    computed_at: str | None = None
    label: str | None = None
    consensus_score: float | None = None
    conviction: float | None = None
    dispersion: float | None = None
    volume: int | None = None
    report_md: str | None = None
    citations: list[Citation] = []
    backtest: Backtest | None = None
    cached: bool | None = None


class CorpusStats(BaseModel):
    items: int


class Health(BaseModel):
    status: str
