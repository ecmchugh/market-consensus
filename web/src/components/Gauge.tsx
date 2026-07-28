import { NEUTRAL_BAND, clamp, signed, toneOf, toneWord } from "../lib/format";

interface Props {
  /** Mean stance, −100…+100. */
  score: number;
  /** Stdev of stance — drawn as a spread band around the needle. */
  dispersion?: number | null;
}

const R = 88;
const CX = 100;
const CY = 100;

/** Point on the gauge arc for a score: −100 → far left, 0 → top, +100 → far right. */
function pt(score: number): [number, number] {
  const t = (Math.PI * (100 - clamp(score, -100, 100))) / 200;
  return [CX + R * Math.cos(t), CY - R * Math.sin(t)];
}

/** Arc path from score `a` to score `b` (a < b sweeps left→right over the top). */
function arc(a: number, b: number): string {
  const [x0, y0] = pt(a);
  const [x1, y1] = pt(b);
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${R} ${R} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

/**
 * The headline read, as a −100…+100 dial.
 *
 * Three things are drawn deliberately:
 *  - the shaded NEUTRAL band, so a near-zero score visibly reads as "no call"
 *    rather than as a weak directional one;
 *  - the value arc measured FROM zero, so length encodes distance from neutral;
 *  - the dispersion spread, because a consensus of −1 with dispersion 47 is a
 *    split crowd, not an indifferent one, and hiding that would misrepresent it.
 */
export default function Gauge({ score, dispersion }: Props) {
  const tone = toneOf(score);
  const toneColor = tone === "bullish" ? "var(--bull)" : tone === "bearish" ? "var(--bear)" : "var(--flat)";
  const [nx, ny] = pt(score);

  const spread = dispersion && dispersion > 0 ? dispersion : 0;
  const lo = clamp(score - spread, -100, 100);
  const hi = clamp(score + spread, -100, 100);

  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 200 116" className="w-full max-w-[280px]" role="img" aria-label={`Consensus ${signed(score, 1)} — ${toneWord(tone)}`}>
        {/* track */}
        <path d={arc(-100, 100)} fill="none" stroke="var(--line)" strokeWidth="9" strokeLinecap="round" />

        {/* the "no directional call" zone */}
        <path d={arc(-NEUTRAL_BAND, NEUTRAL_BAND)} fill="none" stroke="var(--line-strong)" strokeWidth="9" />

        {/* how far apart the crowd is, centered on the read */}
        {spread > 0 && (
          <path d={arc(lo, hi)} fill="none" stroke={toneColor} strokeWidth="9" strokeLinecap="round" opacity="0.16" />
        )}

        {/* the read itself, measured from neutral */}
        <path
          d={score >= 0 ? arc(0, Math.max(score, 0.6)) : arc(Math.min(score, -0.6), 0)}
          fill="none"
          stroke={toneColor}
          strokeWidth="9"
          strokeLinecap="round"
        />

        {/* needle head */}
        <circle cx={nx} cy={ny} r="6.5" fill="var(--surface)" stroke={toneColor} strokeWidth="3.5" />

        {/* end caps */}
        <text x="10" y="114" className="fill-[var(--ink-3)] text-[9px]">
          −100
        </text>
        <text x="163" y="114" className="fill-[var(--ink-3)] text-[9px]">
          +100
        </text>
      </svg>

      <div className="-mt-8 flex flex-col items-center">
        <div className="tnum text-5xl font-light tracking-tight" style={{ color: toneColor }}>
          {signed(score, 1)}
        </div>
        <div className="mt-1 text-sm font-medium" style={{ color: toneColor }}>
          {toneWord(tone)}
        </div>
      </div>
    </div>
  );
}
