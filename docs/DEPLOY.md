# Deploying Market Consensus

**Architecture:** FastAPI on Railway (Docker + a persistent volume for the SQLite
corpus) · static React on Vercel · no external database.

**Why SQLite and not Supabase/pgvector:** the Supabase project is paused and
`SupabaseItemStore` has never been exercised against a live instance. At ~4k items,
SQLite + numpy cosine is genuinely the right tool, and shipping onto an untested
storage backend is a bad first deploy. pgvector stays available behind
`CONSENSUS_BACKEND=supabase` when scale actually demands it.

---

## Before you start

You need a Railway account and a Vercel account. Both CLIs authenticate
interactively, so run these yourself:

```
npm i -g @railway/cli vercel
railway login
vercel login
```

---

## The ordering problem (read this first)

The two services reference each other:

* Vercel needs `VITE_API_BASE` = the **Railway** URL
* Railway needs `ALLOWED_ORIGINS` = the **Vercel** URL (CORS defaults to localhost,
  so an unconfigured deploy is closed, not open)

You cannot satisfy both in one pass. Deploy in this order:

1. Railway → get the API URL
2. Vercel with that URL → get the frontend URL
3. Set `ALLOWED_ORIGINS` on Railway → redeploy

**Between steps 2 and 3 the frontend will be broken with CORS errors. That is
expected**, not a misconfiguration — the API is refusing an origin it hasn't been
told about yet.

---

## 1. API → Railway

```
railway init                 # create the project
railway volume add --mount-path /data
```

The volume is required. Without it the corpus lives in the container filesystem and
every deploy silently wipes all cached readings and accumulated items.

Set variables (via `railway variables --set` or the dashboard):

| Variable | Value | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | your key | **Set this yourself.** Never commit it. |
| `ALLOWED_ORIGINS` | `http://localhost:5173` for now | Updated to the Vercel URL in step 3 |
| `DAILY_COLD_QUERY_BUDGET` | `100` | Global cap on paid cold runs per UTC day |
| `QUERY_RATE_LIMIT` | `20` | Per-IP queries per hour |

`CONSENSUS_DB=/data/corpus.db` is already baked into the Dockerfile — don't override it.

```
railway up
```

Then confirm the boot log shows the corpus was seeded:

```
bootstrap: seeding /data/corpus.db from seed/corpus.seed.db (4019 items, 31 readings)…
```

If instead you see `WARNING no seed … starting with an EMPTY corpus`, the seed
snapshot didn't make it into the image — check that `seed/corpus.seed.db` is
committed (it's exempted in `.gitignore`) and survived `.dockerignore`.

Verify:

```
curl https://<your-app>.up.railway.app/health          # {"status":"ok"}
curl https://<your-app>.up.railway.app/corpus/stats    # {"items":4019}
```

## 2. Frontend → Vercel

```
cd web
vercel link
vercel env add VITE_API_BASE production   # paste the Railway URL, no trailing slash
vercel --prod
```

Vercel's root directory must be `web/`. `web/vercel.json` handles the build and SPA
rewrites.

## 3. Close the CORS loop

```
railway variables --set ALLOWED_ORIGINS=https://<your-app>.vercel.app
railway redeploy
```

Multiple origins are comma-separated (no spaces). Include the preview domain too if
you want preview deploys to work.

---

## Verifying the deploy

1. Load the Vercel URL — the landing page should show the corpus count in the footer.
2. Search a **seeded** subject (Nvidia, TSMC, Bitcoin) → should return in well under
   a second from cache.
3. Search an **unseeded** subject (e.g. "Ford") → runs the full cold path, ~40s.
   This is the riskiest request in the system; see the timeout note below.
4. Confirm CORS is actually closed:
   ```
   curl -i -X OPTIONS https://<api>/subjects/query \
     -H "Origin: https://evil.example" -H "Access-Control-Request-Method: POST"
   ```
   Expect `400` and no `access-control-allow-origin` header.

---

## Known risks

**The 40-second cold request.** `POST /subjects/query` blocks for the whole
pipeline. Railway's edge proxy is the thing most likely to cut it off. If cold
queries fail in production while cached ones work, this is why — and the real fix is
202-and-poll with a job table, not a bigger timeout.

**Cold-start model load.** The embedding model is baked into the image at build time
(`FASTEMBED_CACHE=/opt/models`), so it should NOT download at runtime. If first
requests after a deploy are slow, verify that the build log contains
`embedding model cached into image`.

**Seed drift.** `seed/corpus.seed.db` is a point-in-time snapshot and only applies
to a volume that has no corpus yet. Refreshing it (`cp corpus.db seed/corpus.seed.db`)
adds another ~12MB blob to git history, and it will NOT affect an already-deployed
volume — that one keeps whatever it has accumulated.

**Readings go stale after 24h.** Cached readings expire, so a seeded subject returns
to the slow cold path a day after seeding. A scheduled job re-running
`scripts/seed_corpus.py` keeps the cache warm — not built yet, and it's the same
worker that will later host podcast ingestion.

**Single instance only.** The rate limiter is per-process (`api/limits.py`), so
`numReplicas` above 1 multiplies the effective limit. Keep it at 1 until there's
shared state.
