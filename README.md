# Market Consensus

**Ask what the smart crowd really thinks about any stock, sector, or coin — mined from the podcasts and posts nobody else is systematically listening to, filtered for authenticity, quantified, and checked against what the market actually did.**

Market Consensus turns the *opinion economy* — long-form podcasts, Reddit, newsletters, crypto-native social — into a measurable signal. You ask about a subject ("semiconductors", "NVDA", "Bitcoin", "small-cap biotech"); it mines where that subject is actually being debated, strips out bots and hype, and returns a **quantified conviction read with receipts** — then shows whether that read has historically **led the market or marked the top.**

---

## Why this exists

Ask ChatGPT "what does the public think about semiconductors?" and you get a weak answer. The whole product is being *better than that answer* — and the reason it can be is a checklist of things a chatbot structurally can't do:

| ChatGPT's public-sentiment answer | What Market Consensus does instead |
|---|---|
| Grabs ~5 lucky links | **Systematic sweep** of many posts/threads/episodes |
| Reads SEO'd *articles* | Reads the **raw voice of real people** — Reddit, forums, podcasts |
| A paragraph of vibes | A **quantified, reproducible** score, comparable over time |
| Takes hype at face value | **Filters** bots, shills, and duplicate takes |
| No memory | **Tracks** the trend over time |
| Vague sourcing | **Cites** the exact posts/clips |
| Can't check itself | **Backtests** the read against real price history |

The identity of the project is those verbs — **sweep · filter · quantify · track · cite · test** — done over the layer where the public actually talks. Sources are **pluggable**: Reddit and forums are the crowd; long-form **podcasts** (Whisper-transcribed) are the pundit layer and our hardest-to-copy depth lever. The AI that writes the final report is the *easy* part. The value is the engine feeding it.

---

## How it works (end to end)

```
                 ┌─────────────────────────────────────────────────────┐
                 │  CONTINUOUS (background worker, on a schedule)       │
                 │                                                     │
  podcasts  ─┐   │   ingest → transcribe → tag subjects/tickers →      │
  reddit    ─┤   │   score stance → score authenticity → dedup →       │──┐
  newsletters┼──▶│   embed → store enriched `item`s                    │  │
  farcaster ─┘   │                                                     │  │
                 └─────────────────────────────────────────────────────┘  │
                                                                           ▼
                                                        ┌──────────────────────────────┐
   user asks "semiconductors"  ──────────────────────▶ │  QUERY (fast, on demand)      │
                                                        │                              │
                                                        │  resolve subject → proxy ETF │
                                                        │  semantic search the corpus  │
                                                        │  filter + aggregate stance   │
                                                        │  synthesize report + cite    │
                                                        │  store reading (→ history)   │
                                                        │  overlay price → backtest    │
                                                        └──────────────────────────────┘
                                                                           │
                                                                           ▼
                                                        React dashboard: gauge · trend ·
                                                        report w/ receipts · price overlay
```

**The key design decision:** the expensive work (transcription, scoring) happens **once per item at ingestion**, never per query. A query is a fast semantic search + aggregation over already-processed data. Every query result is **cached as a `subject_reading`**, so the history a backtest needs builds itself over time.

---

## Architecture & stack

| Layer | Tech | Role |
|---|---|---|
| **Ingestion** | Python — podcast RSS/`yt-dlp`, Reddit (`praw`), newsletters, Farcaster API | pull raw content on a schedule |
| **Transcription** | `faster-whisper` (local) or Whisper API | audio → text (the moat) |
| **NLP** | Claude Haiku 4.5 for high-volume tagging/stance; `spaCy` + a ticker dictionary for entity linking; `sentence-transformers` for embeddings | turn text into structured signal |
| **Authenticity** | feature heuristics (account age/reach, burstiness) + near-dup clustering | strip bots/shills/echo |
| **Storage** | Supabase — Postgres + `pgvector` | enriched items, embeddings, cached readings |
| **Report synthesis** | Claude Sonnet (quality, runs once per query) | write the sourced report |
| **Ground truth** | `yfinance` (stocks/ETFs), CoinGecko (crypto) | prices for the backtest |
| **API** | FastAPI (read-only over stored data) | serve the dashboard |
| **Worker** | scheduled job + a small task queue (RQ/Celery or FastAPI background) | continuous ingestion + on-demand subject jobs |
| **Frontend** | React + TypeScript + Tailwind v4 (Vite) | the dashboard |
| **Deploy** | Railway (API + worker), Vercel (frontend), Supabase (data) | |

**Model-cost discipline (matters — this is thousands of LLM calls):** per-item classification runs on a *cheap fast* model (Claude Haiku 4.5) with prompt caching on the shared system prompt; the *expensive strong* model (Claude Sonnet) runs only once per query, for the report. This keeps ingestion affordable while the user-facing output stays high quality.

---

## The pipeline, stage by stage

1. **Ingest** (`ingestion/`) — pull new episodes/posts from a curated source registry. Podcasts via RSS + audio download; Reddit via `praw`; newsletters via RSS/scrape; Farcaster via API. Deduped against what's already stored by source id.
2. **Transcribe** (`pipeline/transcribe.py`) — audio → text with Whisper, split into timestamped segments (so citations can point at `41:20`).
3. **Tag subjects & tickers** (`pipeline/entities.py`) — link each item to the assets/sectors it's about. Handles the hard case: ticker ambiguity ("APE" the token vs. "ape in"), cashtags, company↔ticker↔sector mapping. Dictionary + embeddings + an LLM disambiguation pass.
4. **Score stance** (`pipeline/stance.py`) — direction × conviction (−1…+1), tuned for slang and irony. LLM classification with a fixed rubric so scores are *reproducible*.
5. **Score authenticity** (`pipeline/authenticity.py`) — likelihood a take is organic vs. manufactured (account age/reach, posting cadence, coordination signals). Feeds a weight, not a hard drop.
6. **Dedup** (`pipeline/dedup.py`) — cluster near-identical takes via embeddings so 200 reposts count as one opinion. (This is what makes "consensus" honest.)
7. **Embed & store** (`pipeline/embed.py`, `store.py`) — write the enriched `item` with its vector for later semantic search.
8. **Aggregate on query** (`pipeline/aggregate.py`) — for a subject, gather relevant items, apply authenticity weights, and compute a consensus score, conviction, dispersion, and volume.
9. **Backtest** (`analysis/backtest.py`) — align stored `subject_reading`s to the proxy's forward returns; report lead / coincident / contrarian with a proper train/test split, across many subjects × many days.

---

## Data model (Supabase)

```
source            # registry of what we listen to
  id, kind(podcast|subreddit|newsletter|farcaster), handle, weight, active

item              # one enriched piece of content, processed once
  id, source_id, external_id, url, author, author_reach, published_at
  text_or_transcript, segments(jsonb: [{start,end,text}])   # timestamps for citations
  subjects[]        # ["semiconductors","NVDA"]   ← enables subject search
  stance            # -1..+1 (direction × conviction)
  authenticity      # 0..1 (1 = organic)
  dedup_cluster_id
  embedding vector  # pgvector, for semantic subject match + dedup

subject_reading   # a computed consensus for a subject at a point in time (CACHED → history)
  id, subject, proxy_symbol, computed_at
  consensus_score, conviction, dispersion, volume, authenticity_share
  report_md         # the synthesized write-up
  citations(jsonb)  # [{item_id, source, timestamp, quote}]

price             # cached proxy price series for the backtest
  symbol, date, close
```

`item` is the corpus (built continuously). `subject_reading` is what users see, and it doubles as the historical series the backtest runs on.

---

## API (FastAPI, read-only)

```
GET  /health
POST /subjects/query        { subject }         → run/return a reading (queues work if fresh)
GET  /subjects/{subject}/latest                 → most recent reading (+ report + citations)
GET  /subjects/{subject}/history?days=90        → reading trend over time
GET  /subjects/{subject}/backtest               → signal-vs-price summary
GET  /market/overview                           → roll-up across tracked subjects
GET  /sources                                   → what we're listening to
```

Everything read-only serves precomputed data; `POST /subjects/query` is the one endpoint that can kick off on-demand work (and returns cached instantly if recent).

---

## Frontend (React dashboard)

The dashboard you'll interact with, per subject:

- **Search / subject bar** — type anything; resolves to a subject + its tradeable proxy.
- **Consensus gauge** — the quantified read (e.g. *"Cautiously bullish · 63 · conviction rising"*), framed as a mood/sentiment index, not a forecast.
- **Trend chart** — the subject's conviction over time (from cached readings).
- **The report, with receipts** — the synthesized write-up, every claim linked to a real clip ("BG2 · Aug 3 · 41:20").
- **Authenticity meter** — how much of the raw chatter was filtered as bots/hype (a trust feature, shown openly).
- **Price overlay / backtest panel** — the read against the proxy's price: *did the crowd lead the move or mark the top?* This is the panel that proves the whole thing works.
- **Light/dark, accessible, colorblind-safe** SVG charts.

---

## Project structure

```
market-consensus/
├─ ingestion/          # source pullers
│   ├─ podcasts.py  reddit.py  newsletters.py  farcaster.py  utils.py
├─ pipeline/           # per-item processing (runs once each)
│   ├─ transcribe.py  entities.py  stance.py  authenticity.py
│   ├─ dedup.py  embed.py  aggregate.py  store.py
├─ analysis/
│   ├─ backtest.py  prices.py
├─ api/                # FastAPI (already started)
│   ├─ main.py  models.py
├─ worker/             # scheduling + on-demand jobs
│   ├─ scheduler.py  tasks.py
├─ web/                # React + TS + Tailwind dashboard (already scaffolded)
├─ config.py
└─ README.md
```

---

## Running it

```bash
# 1. Backend deps
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure (see .env.example): Supabase, Anthropic, Reddit, source list
cp .env.example .env

# 3. Kick off ingestion + processing (fills the corpus)
python -m worker.scheduler          # or run once: python -m worker.tasks backfill

# 4. Serve the API
uvicorn api.main:app --reload       # docs at http://localhost:8000/docs

# 5. Frontend
cd web && npm install && npm run dev # http://localhost:5173
```

---

## Roadmap / build order

The discipline: prove one thin vertical slice end-to-end, *then* widen and deepen.

- [ ] **Slice 1 — prove the loop.** One subject ("semiconductors"), one source (a few podcasts), transcribe → tag → stance → aggregate → one reading → chart it against `SOXX`.
- [ ] **Slice 2 — earn the claim.** Backfill a few months of episodes; run the first real backtest (does the read lead the ETF?).
- [ ] **Slice 3 — the moat.** Go deep on ONE hard spike: transcription quality, ticker/subject entity-linking, or authenticity filtering.
- [ ] **Slice 4 — open the box.** Query-by-subject over the corpus (semantic search), cache readings, add the report + citations.
- [ ] **Slice 5 — widen.** Add sources (Reddit, newsletters, Farcaster) and more subjects/sectors.
- [ ] **Slice 6 — ship.** Wire the dashboard, deploy (Railway + Vercel), get real people using it.

---

## Status

This README describes the **target architecture** — the north star we're building toward. Today, the repo has the FastAPI skeleton, a Supabase-backed store, a Reddit scraper, an early backtest harness, and a scaffolded React dashboard. The transcription pipeline, subject-query layer, authenticity scoring, and price-anchored backtest are the work ahead — see the roadmap above.
