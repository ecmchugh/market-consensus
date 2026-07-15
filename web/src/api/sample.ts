import type { ConsensusDay, HistoryPoint } from "./types";

/**
 * Bundled sample data — shaped EXACTLY like the real API responses.
 *
 * Why this exists: the live pipeline currently has sparse data (a single day,
 * no named tickers), which would render an empty dashboard. The app fetches
 * real data first and only falls back to this when the API is unreachable or
 * has nothing yet — so the design is always demoable. A "sample data" badge
 * makes the source obvious; nothing here is presented as real.
 */

const TICKERS = [
  { ticker: "NVDA", score: 72, label: "bullish", mentions: 84, confidence: "high" },
  { ticker: "AMD", score: 54, label: "bullish", mentions: 29, confidence: "medium" },
  { ticker: "AAPL", score: 41, label: "bullish", mentions: 63, confidence: "high" },
  { ticker: "MSFT", score: 38, label: "bullish", mentions: 51, confidence: "high" },
  { ticker: "META", score: 33, label: "bullish", mentions: 38, confidence: "medium" },
  { ticker: "AMZN", score: 29, label: "bullish", mentions: 40, confidence: "medium" },
  { ticker: "GOOGL", score: 12, label: "mixed", mentions: 31, confidence: "medium" },
  { ticker: "JPM", score: 8, label: "mixed", mentions: 22, confidence: "low" },
  { ticker: "TSLA", score: -18, label: "bearish", mentions: 47, confidence: "high" },
  { ticker: "XOM", score: -27, label: "bearish", mentions: 25, confidence: "medium" },
  { ticker: "BA", score: -33, label: "bearish", mentions: 17, confidence: "medium" },
  { ticker: "COIN", score: -41, label: "bearish", mentions: 19, confidence: "low" },
];

export const SAMPLE_LATEST: ConsensusDay = {
  run_date: "2026-07-12",
  consensus_score: 34,
  label: "cautiously bullish",
  confidence: "medium",
  contested: false,
  dispersion: 0.42,
  item_count: 214,
  contributing_count: 18,
  tier_means: { national: 41, financial: 30, social: 22 },
  tickers: TICKERS,
  top_themes: [
    { theme: "September rate-cut odds firm above 70%", count: 63 },
    { theme: "AI datacenter capex re-accelerates", count: 49 },
    { theme: "Energy softens on demand worries", count: 31 },
    { theme: "Consumer spending stays resilient", count: 24 },
    { theme: "China export curbs escalate", count: 19 },
    { theme: "Earnings-season pre-positioning", count: 17 },
  ],
  bull_signals: [
    "Softer CPI print revives September rate-cut bets",
    "Hyperscaler guidance points to a fresh datacenter capex cycle",
    "Card-spending data shows a resilient consumer",
  ],
  bear_signals: [
    "Crude slips as demand forecasts are trimmed",
    "New China export curbs raise supply-chain risk",
  ],
};

/** 30 sessions of overall mood, oldest first — matches /consensus/history. */
export const SAMPLE_HISTORY: HistoryPoint[] = buildHistory();

function buildHistory(): HistoryPoint[] {
  const scores = [
    -8, -3, 2, -5, 4, 9, 6, 12, 7, 15, 11, 18, 14, 9, 16, 21, 17, 13, 19, 24, 20,
    16, 22, 19, 25, 21, 17, 28, 31, 34,
  ];
  const out: HistoryPoint[] = [];
  const d = new Date(2026, 5, 1); // Jun 1, 2026
  let i = 0;
  while (i < scores.length) {
    const g = d.getDay();
    if (g !== 0 && g !== 6) {
      const s = scores[i];
      out.push({
        run_date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
        consensus_score: s,
        label: s >= 18 ? "bullish" : s <= -18 ? "bearish" : "mixed",
        contested: false,
      });
      i++;
    }
    d.setDate(d.getDate() + 1);
  }
  return out;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}
