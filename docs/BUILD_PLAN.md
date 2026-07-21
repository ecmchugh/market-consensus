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

_Last updated: 2026-07-20 — direction locked: production RAG consensus engine (Big Tech resume framing)._

---

## ACTIVE DIRECTION (locked 2026-07-20) — read this first; it supersedes the slice notes below

**What we're building:** an **"ask any market subject" production RAG consensus engine.**
A user submits any tradeable subject (stock / sector / coin, resolved dynamically — no
hardcoded list) → the system mines where it's discussed (HN + Reddit), scores each take
(concurrent Haiku), **retrieves semantically from a stored pgvector corpus**, aggregates
a quantified/deduped/**cited** consensus (Claude Sonnet synthesis), **caches** it, and —
because every subject is tradeable — attaches the **honest price backtest as an
always-on credibility panel**. Deployed live.

**Why this framing (see memory [[bigtech-resume-reframe]], [[product-scope-markets]]):**
recruiting for Big Tech, so resume value = *engineering*, not predictive alpha. The
Slice 1–2 null (no reliable price lead) costs nothing — honest measurement is the story.
Resume surface: RAG + vector search, LLM cost-split (Haiku-for-volume / Sonnet-once +
prompt caching), async throughput, deployed running system. Scope is **markets only** so
the backtest (the hardest-to-fake feature) always applies.

**Two codebases to reconcile:** the WORKING engine is `slice1_prove_loop.py`
(fetch → concurrent Haiku scoring → aggregate → price → chart; concurrency already done).
The `pipeline/` + `api/` + Supabase `daily_consensus` is a legacy news pipeline to
retire/park. Build = graduate the slice-1 monolith into reusable modules.

**Locked decisions:** hybrid coverage (live-fetch novel subjects + accumulate/embed) ·
local sentence-transformers (MiniLM) embeddings · LLM subject-resolver (always → proxy) ·
retire the old news pipeline.

**Build sequence (thin slice first):**
- [x] **P1 — Graduate the engine into modules.** Split the `slice1` monolith into
      `ingestion/sources.py`, `pipeline/stance.py`, `pipeline/aggregate.py`. No behavior
      change; `slice1_prove_loop.py` re-exports the 4 names slice2 needs. Verified:
      imports + slice2 chain + pure-function parity (2026-07-20).
- [x] **P2 — Subject resolver** (`pipeline/subjects.py`): Haiku maps an arbitrary string →
      (search terms, proxy symbol). Verified on stock/sector/crypto/theme (NVDA, URA,
      BTC-USD, QQQ, XBI). Disk-cached. (2026-07-20)
- [x] **P3 — Item storage + embeddings** (`pipeline/embed.py` = fastembed/ONNX MiniLM 384-d;
      `pipeline/itemstore.py` = swappable `ItemStore`; `LocalItemStore` SQLite+numpy cosine
      now, pgvector migration in `db/pgvector_schema.sql` for when Supabase is restored).
      Verified: embed + dedup + semantic ranking. (2026-07-20)
- [x] **P4 — Query path** (`pipeline/query.py`): resolve → fetch-if-thin → score → embed/store
      → semantic search → aggregate → Sonnet cited report → cache. **DEMO WORKS:** "Nvidia"
      → 46 scored items, cited bull/bear brief, cold 24s / cached 0ms. (2026-07-20)
- [x] **P5 — API** (`api/main.py` rewritten): `POST /subjects/query` (cached-if-recent, 422
      for non-market subjects), `GET /subjects/{s}/latest|history|backtest`, `/corpus/stats`,
      `/health`. Legacy `daily_consensus` routes retired. Store made thread-safe for FastAPI's
      threadpool. Verified via TestClient. (2026-07-20)
- [x] **P6 — Backtest as a feature** (`analysis/subject_backtest.py`): per-subject conviction
      vs proxy returns → lead/coincident/lag Pearson r, honest thin-data flagging; wired into
      every financial reading. Verified (NVDA 4-mo: lead −0.33, flagged thin). (2026-07-20)
- [ ] **P7 — Frontend:** wire the paused React dashboard (search → gauge · report w/ receipts · trend · backtest).
- [ ] **P8 — Deploy live:** Railway (API+worker) · Vercel (frontend) · Supabase (data).
      `SupabaseItemStore` (pgvector) is now WRITTEN and gated behind `CONSENSUS_BACKEND=supabase`
      (default stays local SQLite). To activate: restore the paused Supabase project (DNS
      currently doesn't resolve), run `db/pgvector_schema.sql`, set the env var, and verify
      against the live project (the backend has not been exercised end-to-end yet). Then deploy.
- [ ] **P9 — Resume metrics:** cold-vs-cached latency (have: 24s / 0ms), scoring throughput,
      LLM cost/1k, cache-hit rate, corpus size.

---


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

**Active slice:** Slice 2 — monthly/large-cap backtest done (no significant predictive
signal; see finding below). Now testing at WEEKLY resolution (monthly likely too coarse
for a fast signal). Pipeline is now period-aware (month|week) end to end.

**Slice 2 monthly result (24 names × 12 mo, 1811 items):** LEAD r=+0.13 but permutation
p=0.076 (NOT significant), bootstrap CI includes zero, horizon jagged → no reliable
monthly predictive signal. Most robust thread: coincident −0.16 (informed mood leans
CONTRARIAN to same-month move).

**Slice 2 WEEKLY result (10 names × 52 wk, 2528 items, 410 pairs):** clean NULL —
lead r=+0.01 (perm p=0.82), coincident +0.02, lag +0.07, horizon flat at zero, 6/10
positive (coin flip). NOTE: the monthly coincident −0.16 did NOT replicate weekly →
it was likely a small-sample artifact, not a real contrarian structure.

**Cumulative honest conclusion:** HN "informed" sentiment on large-cap tech has NO
detectable relationship to price at monthly OR weekly resolution. Resolution is
exhausted (daily HN volume too thin). The signal, if it exists, isn't here — the
open levers are UNIVERSE (large-cap tech is the most-efficient, hardest case) and
SOURCE (informed ≠ the crowd that moves price). Recommended next experiment: test a
crypto universe (attention-driven, less efficient, HN-discussed, zero-auth via
yfinance BTC-USD/ETH-USD) — directly tests whether the null is a universe artifact.
The "test" verb did its job: it stopped us building a dashboard on a signal that
isn't there. Product value can rest on measurement/aggregation + an HONEST backtest,
not on predictive alpha.

**Slice 2 CRYPTO weekly result (2026-07):** INCONCLUSIVE — a source-coverage wall,
not a signal result. Only 3/10 coins had enough HN volume to test (BTC 172 relevant,
ETH 145, XRP 23); the other 7 were too sparse (ADA 6, LINK 2, DOT 3…). Two causes:
(a) HN is a tech/infra crowd that discusses BTC/ETH but barely covers altcoins;
(b) generic alt names pull homonym noise (Algolia "Cardano" → the mathematician,
"Avalanche" → snow, "Chainlink" → fence), which the stance filter correctly rejects
→ near-zero relevant. Pooled 3-coin lead r=+0.06, perm p=0.71, bootstrap CI
[−0.27, +0.97] — the CI is enormous; this carries ~no information. **Conclusion: HN
cannot test the crypto universe (only BTC/ETH viable). Testing crypto properly needs a
crypto-NATIVE crowd source (Reddit r/CryptoCurrency, Farcaster, StockTwits), which
reopens the source/credentials problem.**

**FORK (2026-07):** predictive-alpha question is now blocked — large-cap = powered
null; crypto = can't cover via HN. Either (A) integrate a crypto-native source to
test crypto for real, or (B) accept the honest accumulated result and pivot to the
product (superior measurement + honest backtest as a credibility feature), where HN's
strong BTC/ETH/AI-infra coverage is genuinely useful. Awaiting user decision.

**Source decision (2026-07):** sources are pluggable and each item carries a
`source_type` — **"informed"** (Hacker News = practitioners/technical crowd, zero-auth)
and **"crowd"** (Reddit = retail public, needs OAuth). We do NOT pick one: the identity
is "honest read of the whole opinion spectrum," and the crowd-vs-informed DIVERGENCE
is a headline signal for later. Published news *articles* stay OUT (that's the
sanitized narrative we're beating, not a voice). Reddit blocked on creds for now, so
HN is Slice 1's default source. (Line: opinion IN, reportage OUT — not expert-vs-public.)

**Slice 1 finding v1 (Reddit, 42 relevant WSB posts / 12 mo):** loop ran end to end,
sensible read; in months with n≥6 conviction tracked price coincidentally, but most
months were too sparse (many n=1) to trust. → motivated the HN pivot. HN gives 40
items/month evenly across 12 months (480 total) with no credentials — data-volume
blocker solved. Verdict pending the HN re-run.

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
| Corpus items `[N]` | 42 relevant / 100 fetched (NVDA, Slice 1) | 2026-07 |
| Hours of audio transcribed | — (no audio yet) | |
| Sources live | 1 (Reddit RSS search, WSB) | 2026-07 |
| % chatter down-weighted `[X]` | — | |
| Cluster-collapse ratio | — | |
| Cached query latency (ms) | cold 24s → cached ~0ms (NVDA, P4) | 2026-07-20 |
| LLM cost / 1k items | ~$0.49–0.69 / 1k (Haiku stance, ~287 in / 41 out tok) | 2026-07-20 |
| Concurrency speedup | 7.7× (16 items 15.7s→2.1s; 0.98s→0.13s/item, 8 workers) | 2026-07-20 |
| Embeddings | 384-dim (fastembed/ONNX MiniLM), local, $0 | 2026-07-20 |
| Prompt-cache NOTE | does NOT fire — stance sys prompt ~250 tok < Haiku 4096 min. Do NOT claim caching as a working optimization. | 2026-07-20 |
| Backtest breadth `[N]×[M]` | wired per-subject (lead/coincident/lag + perm/CI); breadth from Slice 2 = 24×12 | 2026-07-20 |
| **Headline finding (verbatim)** | "Slice 2, 24 large-cap tech names × 12 mo, 1811 HN items, 257 pooled pairs: mood does NOT reliably predict next-month return. LEAD r=+0.13 but permutation p=0.076 (not sig at .05), bootstrap 95% CI [−0.03,+0.28] includes zero, horizon jagged (−0.16 / +0.13 / −0.03). 17/24 names positive. The one robust-ish thread: COINCIDENT r=−0.16 — informed mood leans CONTRARIAN to the same-month move (echoes Slice-1 lag −0.26). Honest verdict: no significant monthly predictive signal on this universe; contrarian structure is the interesting lead." | 2026-07 |

**Slice 1 finding v2 (HN, 202 relevant / 480, 12 mo, NVDA):** loop solid, readings now
trustworthy (n=11–24/mo). Quantified result above. Interpretation: no same-month
relationship; a weak *hint* mood leads price (+0.21) and a weak *hint* the informed
crowd is contrarian to recent moves (−0.26); neither significant at this n. This is the
honest, correct Slice-1 outcome — idea not disproven, not proven; the −0.26 contrarian
lean is the most interesting thread. **Next: Slice 2 breadth (many subjects × months)
turns these hints into a significant test — or kills them.**
Perf note: 480 sequential Haiku calls took ~45 min (~5.6s each) — **Slice 2 needs
concurrent scoring** (asyncio/batching) or it won't scale.
