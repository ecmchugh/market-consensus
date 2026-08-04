import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, fetchCorpusStats, fetchHistory, querySubject } from "./api/client";
import type { Reading } from "./api/types";
import Gauge from "./components/Gauge";
import PriceContext from "./components/PriceContext";
import Progress from "./components/Progress";
import Report from "./components/Report";
import SearchBar from "./components/SearchBar";
import TrendChart from "./components/TrendChart";
import { Card, Pill, Stat } from "./components/ui";
import { signed, stamp, titleCase, toneOf } from "./lib/format";

const EXAMPLES = ["Nvidia", "Bitcoin", "Semiconductors", "Tesla", "Uranium", "AI infrastructure"];

type Phase = "idle" | "loading" | "ready" | "error";

export default function App() {
  const [input, setInput] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [pending, setPending] = useState(""); // subject currently being read
  const [reading, setReading] = useState<Reading | null>(null);
  const [history, setHistory] = useState<Reading[]>([]);
  const [error, setError] = useState<{ status: number; detail: string } | null>(null);
  const [corpus, setCorpus] = useState<number | null>(null);
  const inflight = useRef<AbortController | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    fetchCorpusStats(ac.signal)
      .then((s) => setCorpus(s.items))
      .catch(() => setCorpus(null)); // a down API shouldn't break the landing page
    return () => ac.abort();
  }, []);

  const run = useCallback(async (subject: string, opts: { push?: boolean; force?: boolean } = {}) => {
    inflight.current?.abort();
    const ac = new AbortController();
    inflight.current = ac;

    setPhase("loading");
    setPending(subject);
    setError(null);
    setInput(subject);
    if (opts.push !== false) {
      const url = `${window.location.pathname}?q=${encodeURIComponent(subject)}`;
      window.history.pushState({ q: subject }, "", url);
    }

    try {
      const r = await querySubject(subject, opts.force ?? false, ac.signal);
      if (ac.signal.aborted) return;
      setReading(r);
      setPhase("ready");

      // History is a nice-to-have; a failure here must not sink the reading.
      fetchHistory(r.subject, 90, ac.signal)
        .then((h) => !ac.signal.aborted && setHistory(h))
        .catch(() => setHistory([]));
    } catch (e) {
      if (ac.signal.aborted || (e instanceof DOMException && e.name === "AbortError")) return;
      const err = e instanceof ApiError ? { status: e.status, detail: e.detail } : { status: -1, detail: "Something went wrong." };
      setError(err);
      setPhase("error");
    }
  }, []);

  // Deep-link + back/forward support: ?q=<subject> is the app's whole URL surface.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) void run(q, { push: false });

    function onPop() {
      const next = new URLSearchParams(window.location.search).get("q");
      if (next) void run(next, { push: false });
      else {
        inflight.current?.abort();
        setPhase("idle");
        setReading(null);
        setHistory([]);
        setInput("");
      }
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [run]);

  function goHome() {
    inflight.current?.abort();
    window.history.pushState({}, "", window.location.pathname);
    setPhase("idle");
    setReading(null);
    setHistory([]);
    setError(null);
    setInput("");
  }

  if (phase === "idle") {
    return <Landing input={input} setInput={setInput} onSubmit={(v) => void run(v)} corpus={corpus} />;
  }

  return (
    <div className="min-h-screen bg-bg">
      <header className="sticky top-0 z-10 border-b border-line bg-bg/85 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center gap-4 px-4 py-3">
          <button
            onClick={goHome}
            className="hidden shrink-0 text-[15px] font-semibold tracking-tight text-ink transition-opacity hover:opacity-70 sm:block"
          >
            Market<span className="text-accent">Consensus</span>
          </button>
          <div className="min-w-0 flex-1 sm:max-w-lg">
            <SearchBar value={input} onChange={setInput} onSubmit={(v) => void run(v)} variant="compact" busy={phase === "loading"} />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 pb-20">
        {phase === "loading" && <Progress subject={pending} />}
        {phase === "error" && <ErrorState error={error} subject={pending} onHome={goHome} />}
        {phase === "ready" && reading && (
          <Results reading={reading} history={history} onRefresh={() => void run(reading.input || reading.subject, { push: false, force: true })} />
        )}
      </main>
    </div>
  );
}

function Landing({
  input,
  setInput,
  onSubmit,
  corpus,
}: {
  input: string;
  setInput: (v: string) => void;
  onSubmit: (v: string) => void;
  corpus: number | null;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <div className="flex flex-1 flex-col items-center justify-center px-4 pb-24">
        <div className="w-full max-w-xl animate-rise">
          <h1 className="text-center text-[2.6rem] font-semibold tracking-tight text-ink sm:text-5xl">
            Market<span className="text-accent">Consensus</span>
          </h1>
          <p className="mt-3 text-center text-[15px] leading-relaxed text-ink-2">
            Type any stock, sector, or coin. Get what the crowd actually thinks — measured, quantified, and cited
            back to real posts.
          </p>

          <div className="mt-8">
            <SearchBar value={input} onChange={setInput} onSubmit={onSubmit} autoFocus />
          </div>

          <div className="mt-5 flex flex-wrap justify-center gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => onSubmit(ex)}
                className="rounded-full border border-line bg-surface px-3 py-1.5 text-[13px] text-ink-2 transition-colors hover:border-line-strong hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      </div>

      <footer className="px-4 pb-8 text-center text-xs leading-relaxed text-ink-3">
        <p>
          A sentiment measurement, not investment advice or a price forecast.
          {corpus !== null && <> · {corpus.toLocaleString()} posts in corpus</>}
        </p>
        <p className="mt-1">
          Press <kbd className="rounded border border-line px-1 py-px font-sans text-[10px]">/</kbd> to search
        </p>
      </footer>
    </div>
  );
}

function Results({ reading, history, onRefresh }: { reading: Reading; history: Reading[]; onRefresh: () => void }) {
  const score = reading.consensus_score ?? 0;
  const tone = toneOf(score);
  const toneColor = tone === "bullish" ? "var(--bull)" : tone === "bearish" ? "var(--bear)" : "var(--flat)";

  if (!reading.volume) {
    return (
      <div className="mx-auto max-w-xl animate-rise py-20 text-center">
        <h2 className="text-xl font-medium text-ink">No discussion found for {reading.display ?? reading.subject}</h2>
        <p className="mt-3 text-sm leading-relaxed text-ink-2">
          This subject resolved to a tradeable proxy{reading.proxy ? ` (${reading.proxy})` : ""}, but the sources
          carry too few posts about it to form an honest read. Coverage is strongest on widely-discussed names.
        </p>
      </div>
    );
  }

  return (
    <div className="animate-rise py-6">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{reading.display ?? reading.subject}</h1>
        {reading.proxy && <Pill>{reading.proxy}</Pill>}
        {reading.asset_type && <Pill>{titleCase(reading.asset_type)}</Pill>}
        <div className="ml-auto flex items-center gap-3 text-xs text-ink-3">
          {reading.computed_at && <span>{reading.cached ? "cached · " : ""}read {stamp(reading.computed_at)}</span>}
          <button onClick={onRefresh} className="font-medium text-accent underline-offset-2 hover:underline">
            Re-run
          </button>
        </div>
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)] lg:items-start">
        <div className="order-2 lg:order-1">
          <Card title="What the crowd is saying" hint={`${reading.volume} posts`}>
            {reading.report_md ? (
              <Report md={reading.report_md} citations={reading.citations} />
            ) : (
              <p className="text-sm text-ink-3">No report was generated for this reading.</p>
            )}
          </Card>
        </div>

        <div className="order-1 space-y-5 lg:order-2 lg:sticky lg:top-[68px]">
          <Card title="Consensus">
            <Gauge score={score} dispersion={reading.dispersion} />
            <div className="mt-5 grid grid-cols-3 gap-3 border-t border-line pt-4">
              <Stat label="Conviction" value={reading.conviction?.toFixed(0) ?? "—"} sub="strength of views" />
              <Stat label="Split" value={reading.dispersion?.toFixed(0) ?? "—"} sub="disagreement" />
              <Stat label="Posts" value={reading.volume ?? "—"} sub="scored" />
            </div>
            <p className="mt-4 text-xs leading-relaxed text-ink-3">
              Mean stance of {reading.volume} posts on a −100…+100 scale, currently{" "}
              <span className="tnum font-medium" style={{ color: toneColor }}>
                {signed(score, 1)}
              </span>
              .{" "}
              {(reading.dispersion ?? 0) > 40
                ? "High dispersion — the crowd is split, not indifferent."
                : "Dispersion is moderate; views are relatively aligned."}
            </p>
          </Card>

          {reading.backtest && (
            <Card title="Price context" hint={reading.backtest.proxy ?? undefined}>
              <PriceContext bt={reading.backtest} />
            </Card>
          )}

          <Card title="Trend">
            <TrendChart history={history} />
          </Card>
        </div>
      </div>
    </div>
  );
}

function ErrorState({
  error,
  subject,
  onHome,
}: {
  error: { status: number; detail: string } | null;
  subject: string;
  onHome: () => void;
}) {
  const notMarket = error?.status === 422;
  // The API writes 422/429/503 details to be shown verbatim; these headlines just
  // set the right tone above them (a rate limit isn't a failure, it's a "wait").
  const headline =
    error?.status === 422
      ? `"${subject}" isn't a market subject`
      : error?.status === 429
        ? "Easy — that's a lot of reads"
        : error?.status === 503
          ? "Daily reading limit reached"
          : error?.status === 0
            ? "Can't reach the API"
            : "That read didn't complete";
  return (
    <div className="mx-auto max-w-xl animate-rise py-20 text-center">
      <h2 className="text-xl font-medium text-ink">{headline}</h2>
      <p className="mt-3 text-sm leading-relaxed text-ink-2">{error?.detail}</p>
      {notMarket && (
        <p className="mt-3 text-sm leading-relaxed text-ink-3">
          This covers things that trade — a stock, sector, ETF, or coin — because every reading is anchored to a
          price backtest.
        </p>
      )}
      <button
        onClick={onHome}
        className="mt-6 rounded-full border border-line bg-surface px-4 py-2 text-sm font-medium text-ink transition-colors hover:border-line-strong"
      >
        Try another subject
      </button>
    </div>
  );
}
