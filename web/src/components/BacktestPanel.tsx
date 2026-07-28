import type { Backtest } from "../api/types";
import { periodLabel, signed, strengthOf } from "../lib/format";
import { Caveat } from "./ui";

/** Below this many aligned pairs, a correlation is decorative, not evidence. */
const THIN_PAIRS = 8;

/**
 * Conviction vs. the proxy's price — the honest credibility panel.
 *
 * This project's accumulated finding is that crowd sentiment does NOT reliably
 * predict price (see the Slice 2 nulls in docs/BUILD_PLAN.md). This panel is built
 * to report that faithfully rather than flatter the product: every correlation is
 * shown with the number of pairs behind it, and anything computed from a thin
 * sample is explicitly marked as carrying no weight.
 */
export default function BacktestPanel({ bt }: { bt: Backtest }) {
  const rows = [
    { key: "lead", label: "Leads price", r: bt.lead_r, help: "Read now vs. next period's return" },
    { key: "coincident", label: "Moves with price", r: bt.coincident_r, help: "Read vs. same period's return" },
    { key: "lag", label: "Follows price", r: bt.lag_r, help: "Read vs. last period's return" },
  ] as const;

  const pairs = (k: string) => bt.n_pairs?.[k] ?? 0;
  const thin = rows.every((r) => pairs(r.key) < THIN_PAIRS);

  // `note` is dual-purpose in the backend: sometimes a real caveat ("thin —
  // interpret with caution"), sometimes just a neutral description of what the
  // panel measures. Only the caveat form belongs in the warning box.
  const caveatNote = bt.note && /\bthin\b|too few/i.test(bt.note) ? bt.note : null;

  return (
    <div>
      <p className="text-sm leading-relaxed text-ink-2">
        Does conviction move <em>before</em>, <em>with</em>, or <em>after</em> {bt.proxy ?? "the proxy"}? Pearson{" "}
        <span className="tnum">r</span> over {bt.n_periods ?? "—"} {bt.period ?? "period"}s.
      </p>

      <div className="mt-4 grid grid-cols-3 gap-2">
        {rows.map((row) => {
          const n = pairs(row.key);
          const weak = n < THIN_PAIRS;
          const color = row.r === null ? "var(--ink-3)" : Math.abs(row.r) < 0.1 ? "var(--ink-3)" : row.r > 0 ? "var(--bull)" : "var(--bear)";
          return (
            <div key={row.key} className="rounded-lg border border-line bg-surface-2 px-3 py-2.5" title={row.help}>
              <div className="text-[11px] font-medium leading-tight text-ink-3">{row.label}</div>
              <div className="tnum mt-1.5 text-lg font-medium" style={{ color, opacity: weak ? 0.55 : 1 }}>
                {row.r === null ? "—" : signed(row.r, 2)}
              </div>
              <div className="mt-0.5 text-[10px] leading-tight text-ink-3">
                {/* Don't put a strength word next to a 3-pair correlation — "moderate"
                    would read as a finding. Say why it can't be read instead. */}
                {row.r === null ? "not enough data" : weak ? "too few periods" : strengthOf(row.r)}
                <br />
                <span className="tnum">n={n}</span>
              </div>
            </div>
          );
        })}
      </div>

      {(thin || caveatNote) && (
        <div className="mt-3">
          <Caveat>
            {caveatNote ? `${caveatNote[0].toUpperCase()}${caveatNote.slice(1)}. ` : ""}
            These correlations come from very few aligned periods — they are <strong>not</strong> statistically
            meaningful and are shown for transparency, not as a signal. Broader testing across 24 names × 12 months
            found no reliable predictive relationship.
          </Caveat>
        </div>
      )}

      {bt.series.length > 1 && <SeriesChart series={bt.series} proxy={bt.proxy} />}
    </div>
  );
}

/** Two normalized lines — conviction and proxy price — over the backtest periods. */
function SeriesChart({ series, proxy }: { series: Backtest["series"]; proxy: string | null }) {
  const W = 320;
  const H = 108;
  const PAD = { t: 10, r: 6, b: 20, l: 6 };

  const xs = series.map((_, i) => PAD.l + (i * (W - PAD.l - PAD.r)) / Math.max(series.length - 1, 1));

  /** Map a numeric field to y-pixels using its own min/max — each line has its own scale. */
  function scale(values: (number | null)[]) {
    const nums = values.filter((v): v is number => v !== null && Number.isFinite(v));
    if (!nums.length) return { y: () => null as number | null, min: null, max: null };
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
      y: (v: number | null) => (v === null || !Number.isFinite(v) ? null : H - PAD.b - ((v - min) / (max - min)) * (H - PAD.t - PAD.b)),
      min,
      max,
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

      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Conviction and ${proxy ?? "price"} over ${series.length} periods`}>
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
