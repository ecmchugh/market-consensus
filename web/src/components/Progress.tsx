import { useEffect, useState } from "react";

/**
 * Stages of the cold query path, in the order `pipeline.query.run_query` runs them.
 *
 * IMPORTANT: `secs` are typical durations, not live telemetry. The API is a single
 * blocking POST with no progress channel, so this advances on elapsed time. The
 * stage ORDER and the work described are real; the timing is an estimate, which is
 * why the footer says "typically ~25s" rather than showing a percentage complete.
 * If we ever want true progress, the fix is an SSE endpoint on the backend.
 */
const STAGES = [
  { label: "Resolving subject to a tradeable proxy", secs: 2 },
  { label: "Mining Hacker News for discussion", secs: 5 },
  { label: "Scoring each post's stance (Haiku, concurrent)", secs: 7 },
  { label: "Embedding + semantic retrieval over the corpus", secs: 2 },
  { label: "Synthesizing the cited brief (Sonnet)", secs: 7 },
  { label: "Backtesting conviction against price", secs: 2 },
];

export default function Progress({ subject }: { subject: string }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - started) / 1000), 200);
    return () => clearInterval(id);
  }, []);

  // Walk the stage budget to find where we are.
  let acc = 0;
  const bounds = STAGES.map((s) => {
    const start = acc;
    acc += s.secs;
    return { start, end: acc };
  });
  // Never let the last stage complete on a timer — only the real response ends this.
  const current = Math.min(
    bounds.findIndex((b) => elapsed < b.end) === -1 ? STAGES.length - 1 : bounds.findIndex((b) => elapsed < b.end),
    STAGES.length - 1,
  );

  return (
    <div className="mx-auto max-w-xl animate-rise py-10">
      <div className="flex items-baseline gap-2">
        <h2 className="text-lg font-medium text-ink">Reading the crowd on {subject}</h2>
        <span className="tnum ml-auto text-sm text-ink-3">{elapsed.toFixed(0)}s</span>
      </div>

      <ol className="mt-6 space-y-3">
        {STAGES.map((s, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <li key={s.label} className="flex items-center gap-3">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center">
                {done ? (
                  <svg viewBox="0 0 16 16" className="h-4 w-4 text-bull" aria-hidden="true">
                    <path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : active ? (
                  <svg viewBox="0 0 16 16" className="h-4 w-4 animate-spin text-accent" aria-hidden="true">
                    <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" fill="none" opacity="0.25" />
                    <path d="M14 8a6 6 0 0 0-6-6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" />
                  </svg>
                ) : (
                  <span className="h-1.5 w-1.5 rounded-full bg-line-strong" />
                )}
              </span>
              <span className={`text-sm transition-colors ${done ? "text-ink-3" : active ? "font-medium text-ink" : "text-ink-3"}`}>
                {s.label}
              </span>
            </li>
          );
        })}
      </ol>

      <div className="relative mt-7 h-0.5 overflow-hidden rounded-full bg-line">
        <div className="animate-sweep absolute inset-y-0 w-1/4 rounded-full bg-accent" />
      </div>
      <p className="mt-3 text-xs text-ink-3">
        A first read runs the full pipeline — typically ~25 seconds. Repeat reads are served from cache instantly.
      </p>
    </div>
  );
}
