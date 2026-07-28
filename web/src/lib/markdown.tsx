import type { ReactNode } from "react";

/**
 * A deliberately tiny renderer for the synthesis output — NOT a general markdown
 * library. `report_md` comes from one prompt we control (`_SYNTH_SYSTEM` in
 * `pipeline/query.py`), so it only ever contains paragraphs, `**bold**` runs, and
 * `[n]` citation markers.
 *
 * The reason this is hand-rolled rather than `react-markdown`: the `[n]` markers are
 * the whole point of the feature. They have to become interactive elements wired to
 * the citation list, which means owning the inline parse anyway.
 *
 * Everything is escaped by construction — we build React elements from string slices
 * and never touch `dangerouslySetInnerHTML`.
 */

interface Options {
  /** Called with the citation number when a [n] marker is activated. */
  onCite?: (n: number) => void;
  /** Citation numbers that actually exist, so we don't linkify a stray "[3]". */
  valid?: Set<number>;
}

/** Split a paragraph into text / bold / citation nodes. */
function renderInline(text: string, keyBase: string, opts: Options): ReactNode[] {
  const out: ReactNode[] = [];
  // One pass over both inline forms: **bold** and [n].
  const pattern = /\*\*(.+?)\*\*|\[(\d+)\]/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;

  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));

    if (m[1] !== undefined) {
      out.push(
        <strong key={`${keyBase}-b${i}`} className="font-semibold text-ink">
          {m[1]}
        </strong>,
      );
    } else {
      const n = Number(m[2]);
      if (opts.valid && !opts.valid.has(n)) {
        out.push(m[0]); // no such receipt — render as literal text
      } else {
        out.push(
          <button
            key={`${keyBase}-c${i}`}
            type="button"
            onClick={() => opts.onCite?.(n)}
            title={`Jump to source [${n}]`}
            className="mx-0.5 inline-flex h-[1.15em] min-w-[1.15em] translate-y-[-0.15em] items-center justify-center rounded-[0.3em] border border-accent/25 bg-accent/10 px-[0.28em] align-middle text-[0.68em] font-semibold text-accent transition-colors hover:border-accent/50 hover:bg-accent/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
          >
            {n}
          </button>,
        );
      }
    }
    last = m.index + m[0].length;
    i++;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/**
 * Render the report body. Blank-line-separated blocks become paragraphs; a block
 * that is entirely bold (the model's section headers, e.g. `**Bull case:**`) is
 * promoted to a heading.
 */
export function renderReport(md: string, opts: Options = {}): ReactNode {
  const blocks = md
    .trim()
    .split(/\n{2,}/)
    .map((b) => b.trim())
    .filter(Boolean);

  return blocks.map((block, i) => {
    // Section headers arrive two ways depending on the model's mood: an ATX
    // heading (`## Bull case`) or a fully-bolded line (`**Bull case:**`).
    const atx = /^#{1,4}\s+(.+)$/s.exec(block);
    const wholeBold = /^\*\*(.+)\*\*$/s.exec(block);
    const heading = atx?.[1] ?? wholeBold?.[1];
    if (heading) {
      return (
        <h3 key={i} className="mt-6 text-sm font-semibold tracking-wide text-ink first:mt-0">
          {heading.replace(/\*\*/g, "").trim()}
        </h3>
      );
    }
    // Single newlines inside a block are soft wraps from the model — collapse them.
    const text = block.replace(/\s*\n\s*/g, " ");
    return (
      <p key={i} className="mt-3 leading-[1.75] text-ink-2 first:mt-0">
        {renderInline(text, `p${i}`, opts)}
      </p>
    );
  });
}
