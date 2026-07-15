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

**What exists:**
- FastAPI skeleton with 5 read-only endpoints over Supabase (`api/`).
- Supabase-backed store (`pipeline/store.py`), old news pipeline (`pipeline/`).
- A Reddit scraper (`scrapers/reddit.py`) — reusable for the new direction.
- Early backtest harness against a DJIA headline dataset (`backtest.py`) — to be
  repurposed toward price-anchored subject backtests.
- Scaffolded React + TS + Tailwind dashboard (`web/`) — **paused** until Slice 1
  proves the signal. Do not polish it yet.

**What does NOT exist yet (the new work):**
- Podcast ingestion + Whisper transcription.
- Subject/ticker entity tagging, stance scoring, authenticity scoring, dedup.
- `pgvector` embeddings + subject-query layer + cached `subject_reading`s.
- Price-anchored backtest of conviction vs. forward returns.

**Active slice:** Slice 0 (decisions) → then Slice 1.

---

## Decisions to lock before coding (Slice 0)

_These gate everything; make them first. The podcast list is the one thing Claude
can't pick for you — ask your brother._

- [ ] **Slice-1 subject + proxy:** default **semiconductors → `SOXX`** (concrete,
      podcast-heavy, clean ground truth). Change only with a reason.
- [ ] **Podcast shortlist (3–5)** that regularly discuss semis/tech. Write them in
      `config.py` source registry. ← needs a human with domain taste.
- [ ] **Keys in `.env`:** Anthropic API key, existing Supabase creds. (Whisper runs
      local via faster-whisper; `yfinance` needs no key.)
- [ ] **Transcription choice:** `faster-whisper` local (default, free, slower) vs.
      Whisper API (paid, faster). Default to local for Slice 1.

---

## Slice 1 — Prove the loop  ⟵ FIRST BUILD

_Goal: one subject, a few podcasts, end-to-end, charted against the proxy. If this
shows the read tracks or leads price **at all**, the project is real._

- [ ] **Ingest** (`ingestion/podcasts.py`): read podcast RSS, download recent
      episodes' audio to local scratch. Dedup by episode GUID.
- [ ] **Transcribe** (`pipeline/transcribe.py`): audio → timestamped segments via
      faster-whisper. Store `[{start, end, text}]`. **Capture: hours transcribed.**
- [ ] **Tag relevance** (`pipeline/entities.py` v0): keep segments about semis
      (keyword/dictionary match is fine for v0 — no fancy NLP yet).
- [ ] **Score stance** (`pipeline/stance.py`): Claude Haiku rates each relevant
      segment direction × conviction (−1…+1) with a FIXED rubric (reproducibility).
      Use prompt caching on the system prompt. **Capture: item count, cost/1k.**
- [ ] **Store items** (`pipeline/store.py` extension): write enriched `item` rows
      (see README data model) — subjects, stance, segments, source.
- [ ] **Aggregate** (`pipeline/aggregate.py` v0): roll relevant items into one daily
      "semiconductor conviction" score.
- [ ] **Chart vs. price** (`analysis/prices.py` + a quick plot): pull `SOXX` via
      yfinance, overlay the daily read against the ETF.
- [ ] **LOOK AT IT.** Does the read track / lead / lag price? Write the observation
      down. This is the whole point of Slice 1.

**Exit criteria:** a chart of your conviction read vs. `SOXX`, from real transcribed
podcast audio, with a written first impression.

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
