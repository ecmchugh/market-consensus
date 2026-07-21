-- Market Consensus — pgvector schema (production backend for pipeline/itemstore.py)
--
-- Run this in the Supabase SQL editor once the project is restored. It mirrors the
-- LocalItemStore SQLite schema so SupabaseItemStore can implement the same interface.
-- Vectors are 384-dim to match pipeline/embed.py (BAAI/bge-small-en-v1.5).

create extension if not exists vector;

-- One enriched, embedded opinion — the searchable corpus.
create table if not exists item (
    external_id  text primary key,      -- url / source id; dedup key
    source       text,
    source_type  text,                  -- informed | crowd
    subject      text,                  -- the subject this was fetched for
    title        text,
    text         text,
    author       text,
    url          text,
    timestamp    timestamptz,
    score        integer,               -- stance -100..+100
    rationale    text,
    embedding    vector(384),
    created_at   timestamptz default now()
);

create index if not exists idx_item_subject on item (subject);

-- Approximate-nearest-neighbour index for cosine similarity search.
-- (ivfflat needs ANALYZE + some rows before it helps; fine to create upfront.)
create index if not exists idx_item_embedding
    on item using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- A computed consensus for a subject at a point in time (cached → backtest history).
create table if not exists subject_reading (
    subject         text,
    computed_at     timestamptz default now(),
    label           text,                 -- bullish | neutral | bearish
    consensus_score double precision,
    conviction      double precision,
    dispersion      double precision,
    volume          integer,
    proxy           text,
    is_financial    boolean,
    report_md       text,
    citations       jsonb,
    backtest        jsonb,
    primary key (subject, computed_at)
);

-- Cosine similarity search helper (pgvector's <=> is cosine distance = 1 - similarity).
-- Usage: select * from match_items('[...384 floats...]'::vector, 200, 'NVDA');
create or replace function match_items(query_embedding vector(384), match_count int, filter_subject text default null)
returns setof item
language sql stable
as $$
    select *
    from item
    where embedding is not null
      and (filter_subject is null or subject = filter_subject)
    order by embedding <=> query_embedding
    limit match_count;
$$;
