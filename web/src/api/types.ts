/**
 * Response types mirroring the FastAPI Pydantic models in `api/models.py`.
 * Keep these in lockstep with the backend — they are the contract the whole
 * dashboard binds to.
 *
 * Nearly every field on `Reading` is optional because a reading served from the
 * cache stores fewer fields than a freshly computed one (see the docstring on
 * `api.models.Reading`). Treat anything but `subject`/`is_financial` as maybe-absent.
 */

/** One receipt behind the report — a real post the synthesis cited as [n]. */
export interface Citation {
  n: number;
  source: string;
  url: string | null;
  /** Stance of this post, −100 (very bearish) … +100 (very bullish). */
  score: number;
  quote: string;
}

/** One period in the backtest series: the read, the proxy price, the forward return. */
export interface BacktestPoint {
  period: string;
  conviction: number | null;
  price: number | null;
  /** Fractional return over the period, e.g. 0.0579 = +5.79%. Null where unknown. */
  return: number | null;
}

/**
 * Lead/coincident/lag of conviction vs. the proxy's returns.
 * Correlations are null when there were too few periods to compute honestly —
 * `note` carries the caveat (e.g. "thin — interpret with caution").
 */
export interface Backtest {
  period: string | null;
  n_periods: number | null;
  proxy: string | null;
  lead_r: number | null;
  coincident_r: number | null;
  lag_r: number | null;
  n_pairs: Record<string, number> | null;
  series: BacktestPoint[];
  note: string | null;
}

/** A consensus reading for one market subject — the core object of the whole app. */
export interface Reading {
  /** Canonical store key (the proxy ticker), e.g. "NVDA". */
  subject: string;
  /** Human-facing name from the resolver, e.g. "Nvidia". */
  display: string | null;
  /** Whatever the user actually typed. */
  input: string | null;
  /** Tradeable proxy symbol the backtest runs against. */
  proxy: string | null;
  asset_type: string | null;
  is_financial: boolean;
  computed_at: string | null;
  /** "bullish" | "bearish" | "neutral" — the backend's own bucketing. */
  label: string | null;
  /** Mean stance, −100…+100. The headline number. */
  consensus_score: number | null;
  /** Mean |stance| — how strongly views are held, regardless of direction. */
  conviction: number | null;
  /** Stdev of stance — how much the crowd disagrees. */
  dispersion: number | null;
  /** Number of scored posts behind this reading. */
  volume: number | null;
  report_md: string | null;
  citations: Citation[];
  backtest: Backtest | null;
  cached: boolean | null;
}

export interface CorpusStats {
  items: number;
}

/** Coarse tone bucket derived from a numeric score. Drives color + label everywhere. */
export type Tone = "bullish" | "bearish" | "neutral";
