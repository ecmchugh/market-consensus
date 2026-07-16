# Market Consensus — Build Plan

> **Purpose:** the resumable source of truth for building this project. If this chat
> ends, a new session (or you) starts here. Read `README.md` for the *what/why*;
> this file is the *how/next*. Check boxes as you go and keep the "Current state"
> section honest — it's the first thing to read on resuming.

---

## How to resume (read this first)

1. Read `README.md` (north-star architecture) + this file's **Current state** below.
2. Find the first unchecked task in the **active slice**. That's your next move.
3. Capture any metric the task notes — see `docs/RESUME_TARGETS.md` for why each matters.
4. Update **Current state** and check the box when done.

**The prime directive:** build ONE thin vertical slice fully before widening.
A working weak signal beats a half-built grand architecture. Do not build ahead
of the active slice.

---

## Current state (keep this honest)

_Last updated: 2026-07 — pivot from stock-news sentiment to crypto/stocks crowd-conviction._

**What exists AND is reusable for Reddit-first Slice 1:**
- `scrapers/reddit.py` — OAuth scraper returning score / num_comments / upvote_ratio
  (RSS fallback if no creds). This is both the ingestion path AND the raw signals
  for authenticity scoring later. Reuse nearly as-is.
- `yfinance` already in `requirements.txt` — ground-truth price for the backtest.
- `anthropic` SDK + Supabase store (`pipeline/store.py`) wired up — stance scoring
  + storage ready.
- `config.py` — engagement log-weighting, recency decay, confidence-from-spread,
  min-mention thresholds. Already-considered tuning knobs; carry them forward.
- FastAPI skeleton, 5 read-only endpoints (`api/`).
- Scaffolded React + TS + Tailwind dashboard (`web/`) — **paused** until Slice 1
  proves the signal. Do not polish it yet.
- Old news pipeline + DJIA backtest — repurpose/archive; shape stays, inputs change.

**What does NOT exist yet (the new work):**
- Podcast ingestion + Whisper transcription.
- Subject/ticker entity tagging, stance scoring, authenticity scoring, dedup.
- `pgvector` embeddings + subject-query layer + cached `subject_reading`s.
- Price-anchored backtest of conviction vs. forward returns.

**Active slice:** Slice 0 (decisions) → then Slice 1.

---

## Decisions to lock before coding (Slice 0)

_Reddit-first means fewer gating decisions than the old podcast-first plan —
no podcast list, no Whisper needed to prove the loop._

- [ ] **Slice-1 subject + proxy:** default **`NVDA` → NVDA stock price** — Reddit
      talks in tickers, and a single high-volume name gives the cleanest possible
      ground truth (the stock *is* the proxy, no ETF indirection). Alt: a sector
      like semis → `SOXX` if you'd rather aggregate across names. Change with a reason.
- [ ] **Keys in `.env`:** `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` (scraper falls
      back to RSS without them, but OAuth gives the engagement metadata we want) and
      `ANTHROPIC_API_KEY`. `yfinance` needs no key.
- [ ] _(Deferred to Slice 5)_ Podcast shortlist + faster-whisper — not needed until
      we add audio as source #2.

---

## Slice 1 — Prove the loop  ⟵ FIRST BUILD (Reddit-first)

_Goal: one subject, Reddit text only, end-to-end, charted against the proxy. No
transcription — text is the fast path to a working signal. If the read tracks or
leads price **at all**, the project is real. (Podcasts come in Slice 5.)_

- [ ] **Ingest** (reuse `scrapers/reddit.py`): pull posts from investing subreddits.
      Widen `SUBREDDITS` (add r/wallstreetbets, r/stocks) if targeting a hot ticker.
- [ ] **Filter to subject** (`pipeline/entities.py` v0): keep posts/comments that
      mention the subject (ticker + name/aliases; simple match is fine for v0).
- [ ] **Score stance** (`pipeline/stance.py`): Claude **Haiku** rates each item
      direction × conviction (−1…+1) with a FIXED rubric (reproducibility). Prompt-
      cache the system prompt. **Capture: item count, LLM cost/1k.**
- [ ] **Store items** (extend `pipeline/store.py`): write enriched `item` rows —
      subject, stance, engagement (score/comments/upvote_ratio), source, timestamp.
- [ ] **Aggregate** (`pipeline/aggregate.py` v0): roll items into one daily
      conviction score for the subject (reuse `config.py` engagement/recency weights).
- [ ] **Chart vs. price** (`analysis/prices.py` + quick plot): pull the proxy via
      yfinance, overlay the daily read against price.
- [ ] **LOOK AT IT.** Does the read track / lead / lag price? Write it down. This is
      the entire point of Slice 1.

**Exit criteria:** a chart of your conviction read vs. the proxy price, from real
Reddit data, with a written first impression. No audio yet — that's deliberate.

---

## Slice 2 — Earn the claim (first backtest)

_Goal: turn "looks like it tracks" into a measured statement._

- [ ] Backfill several months of episodes for the Slice-1 subject.
- [ ] Store each historical daily read as a `subject_reading` row.
- [ ] `analysis/backtest.py`: align readings to **forward** returns of the proxy,
      train/test split, test lead / coincident / contrarian.
- [ ] Write the **headline finding verbatim** (even if it's "mostly noise").
      **Capture: N subjects × M days, the split, effect size.**

**Exit criteria:** one honest backtest sentence. → This unlocks resume bullet #4
and already beats the old Consensus bullets. Update the resume here.

---

## Slice 3 — The moat (pick ONE deep spike)

_Goal: the one genuinely hard thing that makes this not-a-template. Pick the one
you'll enjoy grinding — depth is a slog on a spike you don't care about._

- [ ] **Recommended: Authenticity** (`pipeline/authenticity.py` + `dedup.py`) —
      account age/reach + posting-cadence heuristics + embedding near-dup clustering;
      down-weight manufactured hype. Most "Palantir-coded." **Capture: % down-weighted,
      cluster-collapse ratio.**  → resume bullet #2
- [ ] _Alt: Entity-linking_ — crypto/stock ticker disambiguation ("APE" token vs.
      "ape in", cashtags, company↔ticker↔sector).
- [ ] _Alt: Transcription quality_ — diarization, chunking, domain-term accuracy.

**Exit criteria:** the chosen spike measurably changes the output, with before/after
numbers.

---

## Slice 4 — Open the box (subject query + cache)

_Goal: user types any subject → semantic search over the corpus → cached reading.
This completes the architecture story (resume bullet #3)._

- [ ] Add `pgvector`; embed items (`pipeline/embed.py`, sentence-transformers).
- [ ] `pipeline/aggregate.py`: resolve arbitrary subject → proxy symbol; semantic
      search relevant items; aggregate with authenticity weights.
- [ ] Cache as `subject_reading`; `POST /subjects/query` returns cached-if-recent,
      else queues work. **Capture: cold vs. cached latency (ms).**
- [ ] Synthesize the report with citations (Claude Sonnet, once per query).

**Exit criteria:** type a novel subject, get a cited reading; second call is instant.

---

## Slice 5 — Widen

- [ ] Add sources: Reddit (reuse existing scraper), newsletters, Farcaster.
- [ ] Add more subjects/sectors; grow the tracked universe.
- [ ] `GET /market/overview` roll-up across subjects.

## Slice 6 — Ship

- [ ] Wire the paused `web/` dashboard to the real endpoints (gauge, trend, report
      w/ receipts, authenticity meter, price-overlay/backtest panel).
- [ ] Deploy: Railway (API + worker), Vercel (frontend), Supabase (data).
- [ ] Get real people using it. Traction is the one signal nobody can fake.

---

## Parallel housekeeping (low effort, do anytime)

- [ ] Repurpose or archive the old news scrapers + DJIA backtest (shape stays,
      inputs change).
- [ ] Move `web/` polish work to after Slice 1 (don't design a UI for a signal
      that might not pan out).

---

## Metric capture log (fill as earned — see RESUME_TARGETS.md)

| Metric | Value | Captured when |
|---|---|---|
| Corpus items `[N]` | — | |
| Hours of audio transcribed | — | |
| Sources live | — | |
| % chatter down-weighted `[X]` | — | |
| Cluster-collapse ratio | — | |
| Cached query latency (ms) | — | |
| LLM cost / 1k items | — | |
| Backtest breadth `[N]×[M]` | — | |
| **Headline finding (verbatim)** | — | |
