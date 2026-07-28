import { useEffect, useRef, type FormEvent } from "react";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (v: string) => void;
  /** "hero" is the centered landing-page bar; "compact" is the one docked in the header. */
  variant?: "hero" | "compact";
  busy?: boolean;
  autoFocus?: boolean;
}

/**
 * The single input for the whole product: type any market subject, get a reading.
 *
 * Shape is deliberately the familiar search-engine pill — rounded, quiet at rest,
 * lifting on hover/focus — because "type a thing, get an answer" is exactly the
 * interaction, and borrowing a pattern people already know costs no explanation.
 */
export default function SearchBar({ value, onChange, onSubmit, variant = "hero", busy, autoFocus }: Props) {
  const ref = useRef<HTMLInputElement>(null);
  const hero = variant === "hero";

  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  // "/" focuses the bar from anywhere, as long as you're not already typing somewhere.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
      const el = document.activeElement;
      if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) return;
      e.preventDefault();
      ref.current?.focus();
      ref.current?.select();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function submit(e: FormEvent) {
    e.preventDefault();
    const v = value.trim();
    if (v && !busy) onSubmit(v);
  }

  return (
    <form onSubmit={submit} role="search" className="w-full">
      <div
        className={`group flex items-center gap-3 rounded-full border border-line bg-surface transition-shadow duration-150 shadow-bar focus-within:border-transparent focus-within:ring-1 focus-within:ring-accent/40 hover:shadow-bar-active focus-within:shadow-bar-active ${
          hero ? "px-5 py-3.5" : "px-4 py-2"
        }`}
      >
        <SearchIcon className={`shrink-0 text-ink-3 ${hero ? "h-5 w-5" : "h-4 w-4"}`} />

        <input
          ref={ref}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") ref.current?.blur();
          }}
          placeholder={hero ? "Nvidia, bitcoin, semiconductors, uranium…" : "Search a subject"}
          aria-label="Market subject"
          autoComplete="off"
          spellCheck={false}
          enterKeyHint="search"
          className={`min-w-0 flex-1 bg-transparent text-ink placeholder:text-ink-3 focus:outline-none ${
            hero ? "text-lg" : "text-sm"
          }`}
        />

        {value && !busy && (
          <button
            type="button"
            onClick={() => {
              onChange("");
              ref.current?.focus();
            }}
            aria-label="Clear"
            className="shrink-0 rounded-full p-1 text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          >
            <XIcon className={hero ? "h-4 w-4" : "h-3.5 w-3.5"} />
          </button>
        )}

        {busy && <Spinner className={`shrink-0 text-accent ${hero ? "h-4 w-4" : "h-3.5 w-3.5"}`} />}

        <button
          type="submit"
          disabled={!value.trim() || busy}
          className={`shrink-0 rounded-full bg-accent font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-35 hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
            hero ? "px-5 py-2 text-sm" : "px-3.5 py-1.5 text-xs"
          }`}
        >
          Read
        </button>
      </div>
    </form>
  );
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.7" />
      <path d="M13.5 13.5 17 17" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function XIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function Spinner({ className }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" opacity="0.25" />
      <path d="M14 8a6 6 0 0 0-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
