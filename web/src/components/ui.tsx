import type { ReactNode } from "react";

/** Shared surface for every panel on the results page. */
export function Card({
  title,
  hint,
  children,
  className = "",
}: {
  title?: string;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-line bg-surface shadow-card ${className}`}>
      {title && (
        <header className="flex items-baseline justify-between gap-3 border-b border-line px-5 py-3">
          <h2 className="text-xs font-semibold uppercase tracking-[0.07em] text-ink-3">{title}</h2>
          {hint && <div className="text-xs text-ink-3">{hint}</div>}
        </header>
      )}
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

/** A labelled figure. `tone` colors the value for signed/eval-carrying numbers. */
export function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: ReactNode;
  sub?: string;
  tone?: string;
}) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">{label}</div>
      <div className="tnum mt-1 text-xl font-medium text-ink" style={tone ? { color: tone } : undefined}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

export function Pill({ children, tone }: { children: ReactNode; tone?: string }) {
  return (
    <span
      className="inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium"
      style={{
        color: tone ?? "var(--ink-3)",
        borderColor: tone ? `color-mix(in srgb, ${tone} 35%, transparent)` : "var(--line)",
        background: tone ? `color-mix(in srgb, ${tone} 10%, transparent)` : "transparent",
      }}
    >
      {children}
    </span>
  );
}

/** Inline caveat — used wherever the data is too thin to carry a claim. */
export function Caveat({ children }: { children: ReactNode }) {
  return (
    <p className="flex gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs leading-relaxed text-ink-2">
      <span aria-hidden="true" className="text-[var(--flat)]">
        ▲
      </span>
      <span>{children}</span>
    </p>
  );
}
