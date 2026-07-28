import type { Reading } from "../api/types";
import { NEUTRAL_BAND, clamp, shortDate, signed, toneOf } from "../lib/format";

/**
 * Consensus over time, from the cached reading history.
 *
 * Readings accumulate one per query, so this is empty on a subject's first read.
 * Rather than fake a series, it says so — the history is a real byproduct of usage
 * and it's honest to show it building.
 */
export default function TrendChart({ history }: { history: Reading[] }) {
  const pts = history
    .filter((r) => r.consensus_score !== null && r.computed_at)
    .map((r) => ({ t: r.computed_at as string, v: r.consensus_score as number }));

  if (pts.length < 2) {
    return (
      <p className="py-2 text-sm leading-relaxed text-ink-3">
        {pts.length === 1 ? "One reading so far." : "No readings yet."} The trend line builds as this subject is read
        again over time — each query is cached and becomes a point here.
      </p>
    );
  }

  const W = 320;
  const H = 120;
  const PAD = { t: 10, r: 8, b: 20, l: 8 };
  const x = (i: number) => PAD.l + (i * (W - PAD.l - PAD.r)) / (pts.length - 1);
  const y = (v: number) => PAD.t + ((100 - clamp(v, -100, 100)) / 200) * (H - PAD.t - PAD.b);

  const line = pts.map((p, i) => `${i ? "L" : "M"} ${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  const lastTone = toneOf(last.v);
  const lastColor = lastTone === "bullish" ? "var(--bull)" : lastTone === "bearish" ? "var(--bear)" : "var(--flat)";

  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Consensus across ${pts.length} readings`}>
        {/* the neutral band, so drift inside it doesn't read as a directional swing */}
        <rect x={PAD.l} y={y(NEUTRAL_BAND)} width={W - PAD.l - PAD.r} height={y(-NEUTRAL_BAND) - y(NEUTRAL_BAND)} fill="var(--surface-2)" />
        <line x1={PAD.l} y1={y(0)} x2={W - PAD.r} y2={y(0)} stroke="var(--line-strong)" strokeWidth="1" />

        <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {pts.map((p, i) => (
          <circle key={p.t} cx={x(i)} cy={y(p.v)} r={i === pts.length - 1 ? 3.5 : 2.2} fill={i === pts.length - 1 ? lastColor : "var(--accent)"} />
        ))}

        <text x={PAD.l} y={H - 5} className="fill-[var(--ink-3)] text-[9px]">
          {shortDate(pts[0].t)}
        </text>
        <text x={W - PAD.r} y={H - 5} textAnchor="end" className="fill-[var(--ink-3)] text-[9px]">
          {shortDate(last.t)}
        </text>
      </svg>
      <figcaption className="mt-1 flex justify-between text-[11px] text-ink-3">
        <span>{pts.length} readings · shaded band = neutral</span>
        <span className="tnum" style={{ color: lastColor }}>
          latest {signed(last.v, 1)}
        </span>
      </figcaption>
    </figure>
  );
}
