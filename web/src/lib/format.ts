import type { Tone } from "../api/types";

/**
 * Map a numeric sentiment score (−100…+100) to a coarse tone bucket.
 * The ±18 band keeps a wide "mixed" middle so a near-neutral read never
 * masquerades as a directional call.
 */
export function toneOf(score: number): Tone {
  if (score >= 18) return "bullish";
  if (score <= -18) return "bearish";
  return "mixed";
}

/** Human label for a tone, e.g. for the ticker tape chips. */
export function toneWord(tone: Tone): string {
  return tone === "bullish" ? "Bullish" : tone === "bearish" ? "Bearish" : "Mixed";
}

/** Score with an explicit sign, e.g. "+34" / "−12" (real minus glyph). */
export function signed(n: number): string {
  const r = Math.round(n);
  return r > 0 ? `+${r}` : r < 0 ? `−${Math.abs(r)}` : "0";
}

/** Title-case a stored label like "cautiously bullish" → "Cautiously bullish". */
export function titleCase(label: string): string {
  if (!label) return label;
  return label.charAt(0).toUpperCase() + label.slice(1);
}

/** "Jul 12" from an ISO date string (parsed as local, no TZ surprises). */
export function shortDate(iso: string): string {
  const [y, m, d] = iso.split("T")[0].split("-").map(Number);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  if (!y || !m || !d) return iso;
  return `${months[m - 1]} ${d}`;
}

/** Position (0–100%) of a score on a −100…+100 track. */
export function scorePct(score: number): number {
  return ((clamp(score, -100, 100) + 100) / 200) * 100;
}

export function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}
