"""Turn a podcast transcript into passages the stance scorer can actually judge.

This is the hard half of podcast ingestion. Transcription is a solved commodity;
deciding *which* words are about *which* tradeable subject, and handing the scorer a
passage with enough context to carry an opinion, is the part that determines whether
the corpus gains signal or noise.

Two problems, both observed in real transcripts during the spike:

  1. ENTITY AMBIGUITY. Naive substring matching scored "the *intel*ligence actually
     becomes useful" as a mention of Intel. Same failure class that killed Slice 2's
     altcoins (Cardano→the mathematician, Avalanche→snow). Word boundaries fix the
     worst of it; genuinely ambiguous words ("apple", "meta", "arm") need a context
     cue before they count.

  2. FRAGMENT SIZE. Whisper segments averaged 40 characters — nowhere near enough to
     express a stance. A passage has to be built by expanding around a mention until
     there's enough context to argue with.

What this module deliberately does NOT do is decide whether a passage expresses an
opinion. `pipeline.stance` already answers that with its `relevant` flag, the same
way it does for Hacker News posts. The job here is to hand it well-formed candidates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Aliases too generic to identify a subject. The resolver emits some of these
# ("crypto" for Bitcoin, "chips" for semis) and they would match nearly every
# finance conversation, attaching opinions to whichever subject happened to claim
# the word first.
GENERIC_ALIASES = {
    "crypto", "chips", "chip", "stock", "stocks", "shares", "equity", "equities",
    "the market", "markets", "ai", "tech", "software", "hardware", "cloud",
    "digital gold", "coin", "token", "bank", "banks", "oil", "energy",
}

# Aliases that are real English words with common non-financial meanings. These only
# count as a mention when a context cue appears nearby (see CONTEXT_CUES), which
# keeps "an apple a day" and "arm's length" out of the corpus.
AMBIGUOUS_ALIASES = {
    "apple", "meta", "arm", "oracle", "amazon", "alphabet", "intel", "micron",
    "block", "square", "uranium", "target", "shell", "gap",
}

# Words that mark finance/company talk. Used only to rescue AMBIGUOUS_ALIASES.
CONTEXT_CUES = {
    "stock", "stocks", "shares", "share", "earnings", "revenue", "valuation", "market",
    "markets", "cap", "investor", "investors", "buy", "sell", "sold", "bought", "long",
    "short", "bullish", "bearish", "quarter", "guidance", "ipo", "ticker", "trading",
    "trade", "price", "growth", "margin", "margins", "company", "ceo", "profit",
    "billion", "trillion", "percent", "%", "portfolio", "position", "chips", "product",
}

# Mishearings seen in real Whisper output, mapped to the subject key they belong to.
# Kept explicit rather than fuzzy-matched: a typo table is auditable, edit distance
# silently invents matches.
ASR_VARIANTS = {
    "NVDA": ["invidia", "nvidea", "in video"],
    "TSM": ["tsmc", "taiwan semi", "taiwan semiconductor"],
    "AVGO": ["broadcom"],
    "AMD": ["advanced micro devices"],
    "ETH-USD": ["etherium"],
    "SOL-USD": ["salana"],
}

# Passage shaping. ~140 words is roughly a minute of speech — enough for a claim plus
# its justification, short enough that one passage is about one thing.
TARGET_WORDS = 140
MAX_WORDS = 260
MIN_WORDS = 25

# A passage naming this many distinct subjects is almost always a recitation
# ("Nvidia, TSMC, AMD, Micron, all those big names") rather than a view about any
# one of them. Observed directly in the All-In spike.
LIST_SUBJECT_LIMIT = 4


@dataclass
class Segment:
    """One timed unit of transcript. Whisper gives ~40-char fragments; published
    transcripts give speaker turns. Both normalize to this."""
    start: float
    end: float
    text: str
    speaker: str | None = None


def parse_published_transcript(raw: str) -> list[Segment]:
    """Parse the timestamped/diarized format publishers ship, e.g. Odd Lots:

        00:00:18
        Speaker 2: Hello and welcome to another episode...

    These are strictly better input than Whisper output: real speaker turns are
    natural passage boundaries, so no windowing heuristic is needed.
    """
    segs: list[Segment] = []
    blocks = re.split(r"\n(?=\d{2}:\d{2}:\d{2})", raw)
    for block in blocks:
        m = re.match(r"(\d{2}):(\d{2}):(\d{2})\s*\n?(.*)", block.strip(), re.S)
        if not m:
            continue
        h, mnt, s, body = m.groups()
        start = int(h) * 3600 + int(mnt) * 60 + int(s)
        speaker = None
        sm = re.match(r"\s*(Speaker \d+|[A-Z][a-zA-Z .]{1,30}):\s*(.*)", body.strip(), re.S)
        if sm:
            speaker, body = sm.group(1), sm.group(2)
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            segs.append(Segment(start=start, end=start, text=body, speaker=speaker))
    for i, seg in enumerate(segs[:-1]):
        seg.end = segs[i + 1].start
    return segs


def build_alias_index(resolved: dict[str, dict]) -> dict[str, list[str]]:
    """subject key -> spoken aliases, derived from the resolver rather than hardcoded.

    `resolved` maps subject key (proxy ticker) -> the resolver's dict for it. The
    resolver's `aliases` field is a useful starting point but carries descriptions
    ("NVDA competitor", "processor manufacturer") and over-broad terms ("crypto"),
    so it is filtered rather than trusted.
    """
    index: dict[str, list[str]] = {}
    for key, r in resolved.items():
        cands = [r.get("display", ""), *(r.get("aliases") or []), *ASR_VARIANTS.get(key, [])]
        out: set[str] = set()
        for c in cands:
            c = (c or "").strip().lower()
            c = re.sub(r"\b(inc|corp|corporation|plc|ltd|co)\b\.?", "", c).strip(" .,")
            if not c or c in GENERIC_ALIASES:
                continue
            # Descriptions, not names — the resolver emits these and they never
            # appear in speech, but they'd add noise to the pattern set.
            if re.search(r"\b(competitor|manufacturer|industry|maker|stock)\b", c) and " " in c:
                continue
            if len(c) < 3:
                continue
            out.add(c)
        if out:
            index[key] = sorted(out, key=len, reverse=True)
    return index


def _cue_nearby(text_lc: str, at: int, window: int = 220) -> bool:
    """Is there finance/company vocabulary near this position?"""
    ctx = text_lc[max(0, at - window): at + window]
    return any(re.search(rf"\b{re.escape(w)}\b", ctx) for w in CONTEXT_CUES)


def find_subjects(text: str, alias_index: dict[str, list[str]]) -> set[str]:
    """Subject keys genuinely mentioned in `text`.

    Word-boundary matched. Ambiguous common words additionally require a nearby
    context cue, so "an apple a day" doesn't become an AAPL opinion.
    """
    lc = text.lower()
    found: set[str] = set()
    for key, aliases in alias_index.items():
        for alias in aliases:
            for m in re.finditer(rf"\b{re.escape(alias)}\b", lc):
                if alias in AMBIGUOUS_ALIASES and not _cue_nearby(lc, m.start()):
                    continue
                found.add(key)
                break
            if key in found:
                break
    return found


def build_passages(segments: list[Segment], alias_index: dict[str, list[str]], *,
                   episode: dict | None = None) -> list[dict]:
    """Expand each subject mention into a passage with enough context to score.

    Returns one record per (passage, subject) pair, shaped like the records
    `ingestion.sources` produces so the rest of the pipeline is unchanged. A passage
    discussing two subjects is emitted twice — the `item` table keys one subject per
    row, and duplicating is cheaper than reshaping the schema.
    """
    episode = episode or {}
    out: list[dict] = []
    seen: set[tuple[str, int]] = set()

    for i, seg in enumerate(segments):
        hits = find_subjects(seg.text, alias_index)
        if not hits:
            continue

        # Expand outward until the passage carries enough context.
        lo = hi = i
        words = len(seg.text.split())
        while words < TARGET_WORDS and (lo > 0 or hi < len(segments) - 1):
            grew = False
            if lo > 0:
                lo -= 1
                words += len(segments[lo].text.split())
                grew = True
            if words < TARGET_WORDS and hi < len(segments) - 1:
                hi += 1
                words += len(segments[hi].text.split())
                grew = True
            if not grew or words >= MAX_WORDS:
                break

        text = " ".join(s.text for s in segments[lo:hi + 1]).strip()
        if len(text.split()) < MIN_WORDS:
            continue

        # Re-detect over the FULL passage: context may disambiguate a mention the
        # single fragment couldn't, and may reveal it's a list recitation.
        passage_subjects = find_subjects(text, alias_index)
        if len(passage_subjects) > LIST_SUBJECT_LIMIT:
            continue

        for key in passage_subjects & hits:
            bucket = int(segments[lo].start // 60)
            if (key, bucket) in seen:      # one passage per subject per minute
                continue
            seen.add((key, bucket))
            out.append({
                "external_id": f"{episode.get('guid', 'ep')}:{key}:{int(segments[lo].start)}",
                "source": episode.get("show", "podcast"),
                "source_type": "podcast",
                "subject": key,
                "title": episode.get("title", ""),
                "text": text,
                "url": episode.get("url"),
                "timestamp": episode.get("published"),
                "start_s": segments[lo].start,
                "speaker": seg.speaker,
            })
    return out
