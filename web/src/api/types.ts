/**
 * Response types mirroring the FastAPI Pydantic models in `api/models.py`.
 * Keep these in lockstep with the backend — they are the contract the whole
 * dashboard binds to.
 */

/** One entry in `top_themes` — a recurring topic and how often it surfaced. */
export interface Theme {
  theme: string;
  count: number;
}

/**
 * Per-ticker read for a day. Note we surface `label` (the tone) and `mentions`,
 * NOT the raw `score` — this is a mood gauge, not a price call.
 */
export interface TickerSentiment {
  ticker: string;
  score: number;
  label: string;
  mentions: number;
  confidence: string;
}

/** One day in the trend series — just what the chart needs. */
export interface HistoryPoint {
  run_date: string;
  consensus_score: number;
  label: string;
  contested: boolean;
}

/** The full consensus for a single day (`/consensus/latest`, `/consensus/{date}`). */
export interface ConsensusDay {
  run_date: string;
  consensus_score: number;
  label: string;
  confidence: string;
  contested: boolean;
  dispersion: number;
  item_count: number;
  contributing_count: number;
  tier_means: Record<string, number>;
  tickers: TickerSentiment[];
  top_themes: Theme[];
  bull_signals: string[];
  bear_signals: string[];
}

/** Coarse tone bucket derived from a numeric score. Drives color + label everywhere. */
export type Tone = "bullish" | "bearish" | "mixed";

/** Where the currently displayed data came from — surfaced subtly in the UI. */
export type DataSource = "live" | "sample";
