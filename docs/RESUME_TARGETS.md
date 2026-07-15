# Market Consensus — Target Resume Bullets

**Rule: nothing from this file goes on the resume until its "Earned when" line is true.**
Written in present tense so it reads like the finished resume entry you're building toward.
Metrics in `[brackets]` are numbers you must capture while building — log them as you go,
they're much harder to reconstruct later.

---

## The header

**Market Consensus** | *Python, FastAPI, Supabase (Postgres + pgvector), Whisper, React/TypeScript*
Crowd-Conviction Index for Stocks & Crypto

---

## The four bullets

### 1. The dark-data moat (ingestion + transcription)

> Built an end-to-end platform that continuously ingests and Whisper-transcribes
> long-form finance podcasts alongside Reddit, newsletter, and Farcaster content,
> converting untranscribed audio into a searchable corpus of [N] scored,
> timestamp-cited items

- **Earned when:** Slice 1 running end-to-end (real podcast audio → transcript →
  stored items with timestamped segments), plus at least one text source live.
- **Capture:** total items in corpus, hours of audio transcribed, number of sources.
- **Interview depth to have ready:** why faster-whisper vs. API, how you chunk
  segments for citations, RSS/yt-dlp ingestion quirks.

### 2. The Palantir bullet (adversarial data / authenticity)

> Engineered an authenticity-weighting layer — account age/reach and posting-cadence
> heuristics plus embedding-based near-duplicate clustering — that separates organic
> conviction from bot and coordinated-hype activity, down-weighting [X]% of raw
> chatter so 200 reposts count as one opinion

- **Earned when:** Slice 3, if you pick authenticity as your deep spike (recommended —
  adversarial-data work is the most Palantir-coded thing in this project).
- **Capture:** share of items down-weighted/clustered, cluster-collapse ratio,
  any before/after effect on the consensus score.
- **Interview depth:** what coordination signals you chose and why, failure modes,
  how you validated the filter wasn't killing real signal.

### 3. The systems-design bullet (architecture)

> Designed a precompute-at-ingestion, serve-instantly architecture — scheduled
> workers run LLM stance scoring and entity linking once per item into Postgres +
> pgvector, so subject queries execute as semantic search and aggregation, returning
> cached readings in [X] ms

- **Earned when:** Slice 4 (query-by-subject over the corpus with cached
  `subject_reading`s) is working.
- **Capture:** cold vs. cached query latency, corpus size at time of measurement,
  LLM cost per 1k items (the Haiku-for-volume / Sonnet-once-per-query split with
  prompt caching is a great cost-engineering talking point even if it doesn't
  make the bullet).
- **Interview depth:** why rollups/caching instead of per-query scraping, schema
  trade-offs, how the reading cache doubles as backtest history.

### 4. The earned-claim bullet (backtest)

> Backtested stored conviction readings against forward returns of tradeable
> proxies (yfinance, CoinGecko) across [N] subjects × [M] days with a train/test
> split, finding [your honest result — e.g. "conviction acts as a contrarian
> signal at extremes"]

- **Earned when:** Slice 2 — a real backtest run on real stored readings.
  A weak or negative finding still counts; "measured honestly, found mostly noise"
  is a *better* interview story than an asserted vibe.
- **Capture:** N subjects, M days, the split, the headline finding, effect size.
- **Interview depth:** why forward returns, leakage risks, why breadth matters
  for statistical power. This bullet rhymes with your Booko randomized-holdout
  story — that's deliberate; together they say "I test my systems against
  ground truth."

---

## Alternate / bench bullet (swap in if one above underdelivers)

> Cut per-item LLM classification costs by [X]% by routing high-volume tagging
> and stance scoring to Claude Haiku with prompt caching while reserving a
> stronger model for once-per-query report synthesis

- **Earned when:** you've actually measured the cost delta.

---

## Priority order (resume value per hour of work)

1. **Slice 1 + 2** — the moment a backtest number exists, this project already
   beats the current Consensus bullets. Update the resume here, even if bullets
   2 and 3 aren't earned yet.
2. **Slice 3 (authenticity spike)** — biggest differentiation for Palantir.
3. **Slice 4** — completes the architecture story.
4. Slices 5–6 widen numbers but don't add new bullet types.

## What each capture metric replaces

| Placeholder | Where you'll get it |
|---|---|
| [N] corpus items / hours transcribed | count query on `item` table / sum of segment durations |
| [X]% chatter down-weighted | authenticity + dedup stats over the corpus |
| [X] ms query latency | time the cached `GET /subjects/{s}/latest` path |
| [N] × [M] backtest breadth | rows in `subject_reading` joined to `price` |
| headline finding | `analysis/backtest.py` output — write it down verbatim |
