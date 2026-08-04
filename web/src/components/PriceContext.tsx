import type { Backtest } from "../api/types";
import { pct, periodLabel, signed } from "../lib/format";

/**
 * How conviction has moved alongside the proxy's price.
 *
 * This replaced a panel that reported lead/coincident/lag Pearson correlations.
 * Two reasons it had to go, and they compound:
 *
 *   1. WRONG CLAIM. This product measures what the crowd thinks — it does not
 *      forecast price. Printing correlation coefficients invited a question the
 *      project never set out to answer.
 *   2. WRONG NUMBERS. Per-subject histories run ~11 monthly periods. An r of −0.44
 *      at n=11 carries p≈0.18; the panel was labelling that "weak" with no caveat,
 *      i.e. presenting noise as a finding. Across 24 names × 12 months the pooled
 *      tests returned no significant relationship at all (p=0.076 monthly,
 *      p=0.82 weekly).
 *
 * What survives is the part that was always honest: the two series side by side,
 * plus a plain factual statement of what each did over the window. No claim is made
 * that one explains the other. `analysis/subject_backtest.py` still computes the
 * correlations — they belong in the analysis write-up, not in a product surface
 * where a passing reader would take them for a signal.
 */
export default function PriceContext({ bt }: { bt: Backtest }) {
  const pts = bt.series.filter((p) => p.conviction !== null || p.price !== null);
  const convs = pts.filter((p) => p.conviction !== null);
  const prices = pts.filter((p) => p.price !== null);

  const dConv =
    convs.length > 1 ? (convs[convs.length - 1].conviction as number) - (convs[0].conviction as number) : null;
  const dPrice =
    prices.length > 1
      ? ((prices[prices.length - 1].price as number) - (prices[0].price as number)) / (prices[0].price as number)
      : null;

  const span =
    pts.length > 1 ? `${periodLabel(pts[0].period)} – ${periodLabel(pts[pts.length - 1].period)}` : null;

  return (
    <div>
      <p className="text-sm leading-relaxed text-ink-2">
        How the crowd's conviction has moved alongside {bt.proxy ?? "the proxy"}
        {span ? `, ${span}` : ""}.
      </p>

      {(dConv !== null || dPrice !== null) && (
        <div className="mt-4 grid grid-cols-2 gap-3">
          <Delta
            label="Conviction"
            value={dConv === null ? "—" : `${signed(dConv, 1)} pts`}
            tone={dConv === null ? undefined : dConv > 0 ? "var(--bull)" : dConv < 0 ? "var(--bear)" : undefined}
            sub="change over the window"
          />
          <Delta
            label={bt.proxy ?? "Price"}
            value={dPrice === null ? "—" : pct(dPrice)}
            tone={dPrice === null ? undefined : dPrice > 0 ? "var(--bull)" : dPrice < 0 ? "var(--bear)" : undefined}
            sub="change over the window"
          />
        </div>
      )}

      {bt.series.length > 1 && <SeriesChart series={bt.series} proxy={bt.proxy} />}

      <p className="mt-4 border-t border-line pt-3 text-xs leading-relaxed text-ink-3">
        Shown as context, not a forecast. Testing across 24 names over 12 months found no reliable
        relationship between crowd conviction and subsequent price moves.
      </p>
    </div>
  );
}

function Delta({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface-2 px-3 py-2.5">
      <div className="text-[11px] font-medium leading-tight text-ink-3">{label}</div>
      <div className="tnum mt-1.5 text-lg font-medium" style={tone ? { color: tone } : undefined}>
        {value}
      </div>
      <div className="mt-0.5 text-[10px] leading-tight text-ink-3">{sub}</div>
    </div>
  );
}

/** Two normalized lines — conviction and proxy price — over the same periods. */
function SeriesChart({ series, proxy }: { series: Backtest["series"]; proxy: string | null }) {
  const W = 320;
  const H = 108;
  const PAD = { t: 10, r: 6, b: 20, l: 6 };

  const xs = series.map((_, i) => PAD.l + (i * (W - PAD.l - PAD.r)) / Math.max(series.length - 1, 1));

  /** Map a numeric field to y-pixels using its own min/max — each line has its own scale. */
  function scale(values: (number | null)[]) {
    const nums = values.filter((v): v is number => v !== null && Number.isFinite(v));
    if (!nums.length) return { y: () => null as number | null };
    let min = Math.min(...nums);
    let max = Math.max(...nums);
    if (min === max) {
      min -= 1;
      max += 1;
    }
    const pad = (max - min) * 0.12;
    min -= pad;
    max += pad;
    return {
      y: (v: number | null) =>
        v === null || !Number.isFinite(v) ? null : H - PAD.b - ((v - min) / (max - min)) * (H - PAD.t - PAD.b),
    };
  }

  const conv = scale(series.map((p) => p.conviction));
  const price = scale(series.map((p) => p.price));

  function path(y: (v: number | null) => number | null, field: "conviction" | "price") {
    const pts: string[] = [];
    series.forEach((p, i) => {
      const yy = y(p[field]);
      if (yy === null) return;
      pts.push(`${pts.length ? "L" : "M"} ${xs[i].toFixed(1)} ${yy.toFixed(1)}`);
    });
    return pts.join(" ");
  }

  const first = series[0]?.period;
  const last = series[series.length - 1]?.period;

  return (
    <figure className="mt-5">
      <figcaption className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-3">
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded-full bg-accent" aria-hidden="true" />
          Conviction
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="16" height="2" aria-hidden="true">
            <line x1="0" y1="1" x2="16" y2="1" stroke="var(--ink-3)" strokeWidth="2" strokeDasharray="3 2.5" />
          </svg>
          {proxy ?? "Price"}
        </span>
        <span className="ml-auto">each line scaled to its own range</span>
      </figcaption>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label={`Conviction and ${proxy ?? "price"} over ${series.length} periods`}
      >
        <path d={path(price.y, "price")} fill="none" stroke="var(--ink-3)" strokeWidth="1.6" strokeDasharray="3 2.5" strokeLinejoin="round" />
        <path d={path(conv.y, "conviction")} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {series.map((p, i) => {
          const yy = conv.y(p.conviction);
          return yy === null ? null : <circle key={p.period} cx={xs[i]} cy={yy} r="2.6" fill="var(--accent)" />;
        })}
        {first && (
          <text x={PAD.l} y={H - 6} className="fill-[var(--ink-3)] text-[9px]">
            {periodLabel(first)}
          </text>
        )}
        {last && (
          <text x={W - PAD.r} y={H - 6} textAnchor="end" className="fill-[var(--ink-3)] text-[9px]">
            {periodLabel(last)}
          </text>
        )}
      </svg>
    </figure>
  );
}
