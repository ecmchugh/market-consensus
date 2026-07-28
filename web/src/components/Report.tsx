import { useCallback, useEffect, useRef, useState } from "react";

import type { Citation } from "../api/types";
import { signed } from "../lib/format";
import { renderReport } from "../lib/markdown";

interface Props {
  md: string;
  citations: Citation[];
}

const SOURCE_LABEL: Record<string, string> = {
  hackernews: "Hacker News",
  reddit: "Reddit",
};

/**
 * The synthesized brief plus its receipts.
 *
 * The point of this panel is that every claim is traceable: each `[n]` in the text
 * is a live control that jumps to the actual post it came from. That is the whole
 * argument against "the LLM said so" — the sources are one click away, with the
 * stance score the model assigned, and a link to the original.
 */
export default function Report({ md, citations }: Props) {
  const [active, setActive] = useState<number | null>(null);
  const refs = useRef(new Map<number, HTMLLIElement>());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), []);

  const jump = useCallback((n: number) => {
    const el = refs.current.get(n);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    setActive(n);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setActive(null), 2200);
  }, []);

  const valid = new Set(citations.map((c) => c.n));

  return (
    <div>
      <div className="text-[15px]">{renderReport(md, { onCite: jump, valid })}</div>

      {citations.length > 0 && (
        <>
          <h3 className="mt-8 border-t border-line pt-5 text-xs font-semibold uppercase tracking-[0.07em] text-ink-3">
            Sources · {citations.length} posts cited
          </h3>
          <ol className="mt-3 space-y-1.5">
            {citations.map((c) => {
              const tone = c.score > 0 ? "var(--bull)" : c.score < 0 ? "var(--bear)" : "var(--flat)";
              return (
                <li
                  key={c.n}
                  ref={(el) => {
                    if (el) refs.current.set(c.n, el);
                    else refs.current.delete(c.n);
                  }}
                  className={`rounded-lg border px-3 py-2.5 transition-colors duration-300 ${
                    active === c.n ? "border-accent/50 bg-accent/[0.07]" : "border-transparent hover:bg-surface-2"
                  }`}
                >
                  <div className="flex gap-3">
                    <span className="tnum mt-px shrink-0 text-xs font-semibold text-ink-3">[{c.n}]</span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm leading-relaxed text-ink-2">{c.quote}</p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-ink-3">
                        <span>{SOURCE_LABEL[c.source] ?? c.source}</span>
                        <span aria-hidden="true">·</span>
                        <span className="tnum font-medium" style={{ color: tone }}>
                          stance {signed(c.score)}
                        </span>
                        {c.url && (
                          <>
                            <span aria-hidden="true">·</span>
                            <a
                              href={c.url}
                              target="_blank"
                              rel="noreferrer noopener"
                              className="font-medium text-accent underline-offset-2 hover:underline"
                            >
                              view original ↗
                            </a>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </>
      )}
    </div>
  );
}
