import type { Tone } from "../api/types";

/**
 * Width of the "neutral" band around zero. Mirrors `NEUTRAL_BAND` in
 * `pipeline/query.py` so the UI never labels a reading differently from the
 * backend's own `label` field.
 */
export const NEUTRAL_BAND = 15;

/** Map a mean stance score (−100…+100) to a coarse tone bucket. */
export function toneOf(score: number): Tone {
  if (score > NEUTRAL_BAND) return "bullish";
  if (score < -NEUTRAL_BAND) return "bearish";
  return "neutral";
}

/** Human label for a tone. */
export function toneWord(tone: Tone): string {
  return tone === "bullish" ? "Bullish" : tone === "bearish" ? "Bearish" : "Neutral";
}

/** Score with an explicit sign, e.g. "+34" / "−12" (real minus glyph). */
export function signed(n: number, digits = 0): string {
  const r = Number(n.toFixed(digits));
  if (r > 0) return `+${r.toFixed(digits)}`;
  if (r < 0) return `−${Math.abs(r).toFixed(digits)}`;
  return r.toFixed(digits);
}

/** Fractional return → percent string, e.g. 0.0579 → "+5.8%". */
export function pct(fraction: number, digits = 1): string {
  return `${signed(fraction * 100, digits)}%`;
}

/** Title-case a stored label like "bullish" → "Bullish". */
export function titleCase(label: string): string {
  if (!label) return label;
  return label.charAt(0).toUpperCase() + label.slice(1);
}

/** "Jul 12" from an ISO date/datetime string (date part parsed as local, no TZ surprises). */
export function shortDate(iso: string): string {
  const [y, m, d] = iso.split("T")[0].split("-").map(Number);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  if (!y || !m || !d) return iso;
  return `${months[m - 1]} ${d}`;
}

/** "Jul 20, 11:23 PM" — for the "computed at" stamp on a reading. */
export function stamp(iso: string): string {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** "2026-04" → "Apr 2026"; passes anything else through unchanged. */
export function periodLabel(period: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(period);
  if (!m) return period;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[Number(m[2]) - 1]} ${m[1]}`;
}

/** Position (0–100%) of a score on a −100…+100 track. */
export function scorePct(score: number): number {
  return ((clamp(score, -100, 100) + 100) / 200) * 100;
}

export function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

/**
 * Plain-English strength of a Pearson r. Deliberately conservative — this project's
 * honest finding is that these correlations are weak, and the UI should not dress
 * a noisy r up as a result.
 */
export function strengthOf(r: number): string {
  const a = Math.abs(r);
  if (a < 0.1) return "no relationship";
  if (a < 0.3) return "very weak";
  if (a < 0.5) return "weak";
  if (a < 0.7) return "moderate";
  return "strong";
}
