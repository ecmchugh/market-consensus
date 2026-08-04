"""Podcast ingestion — spoken market opinion, as a third source alongside HN.

Forward-only by design. Measured cadence across the configured shows is ~0.5
relevant episodes/day, so keeping current costs ~4 minutes of transcription a night.
Backfilling the same shows would be ~400 compute-hours for history the backtest
already gets from Hacker News, so it isn't attempted.

Pipeline per episode:

    feed  ->  new?  ->  names a covered subject?  ->  get text  ->  passages
             (guid)      (title/description)        (published
              state)                                 transcript,
                                                     else Whisper)

Two cost controls, both measured during the spike rather than assumed:

  * METADATA PRE-FILTER. Only 27% of episodes name a subject we track. Checking the
    title and description costs nothing and avoids transcribing the other 73%.
  * FREE TRANSCRIPTS FIRST. Some publishers ship transcripts in the feed via the
    Podcasting 2.0 <podcast:transcript> tag (Odd Lots does, for all 1251 episodes).
    Those are better input than Whisper — real speaker turns instead of 40-char
    fragments — and cost zero compute.

Whisper is imported lazily so this module works for transcript-publishing shows
without the transcription stack installed (see requirements-ingest.txt).
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from pipeline.transcript import Segment, build_passages, parse_published_transcript

UA = {"User-Agent": "Mozilla/5.0 (compatible; market-consensus/0.2; +research)"}

# Shows are configured by NAME and resolved to feeds through Apple's public search
# API, so the config doesn't rot when a publisher moves hosts.
DEFAULT_SHOWS = [
    "All-In Podcast",        # markets/tech panel — highest yield of covered subjects
    "Odd Lots",              # macro; publishes free transcripts
    "Animal Spirits Podcast",
    "BG2Pod",
    "Acquired",
]

WHISPER_MODEL = "small"   # 11x realtime on CPU at int8; ~9 min for a 97-min episode
MAX_AUDIO_MB = 400        # refuse absurd downloads


@dataclass
class Episode:
    guid: str
    show: str
    title: str
    published: str | None
    audio_url: str | None
    transcript_url: str | None
    description: str = ""
    _segments: list[Segment] = field(default_factory=list, repr=False)


def _get(url: str, timeout: int = 60) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def discover_feed(show_name: str) -> str | None:
    """Podcast name -> RSS url via the public iTunes Search API (no key required)."""
    q = urllib.parse.urlencode({"term": show_name, "entity": "podcast", "limit": 5})
    try:
        data = json.loads(_get(f"https://itunes.apple.com/search?{q}", timeout=30))
    except Exception:
        return None
    for item in data.get("results", []):
        if item.get("feedUrl"):
            return item["feedUrl"]
    return None


def _tag(block: str, name: str) -> str:
    m = re.search(rf"<{name}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{name}>", block, re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def list_episodes(feed_url: str, show: str, limit: int = 40) -> list[Episode]:
    """Recent episodes from a feed, newest first.

    Parsed with regex rather than feedparser because the <podcast:transcript> tag
    lives in a namespace feedparser drops, and that tag is what makes free
    transcripts reachable.
    """
    try:
        raw = _get(feed_url).decode("utf-8", "ignore")
    except Exception:
        return []

    out: list[Episode] = []
    for block in re.split(r"<item[ >]", raw)[1:][:limit]:
        guid = _tag(block, "guid") or _tag(block, "link")
        if not guid:
            continue
        audio = re.search(r'<enclosure[^>]*url="([^"]+)"[^>]*type="audio', block) or \
            re.search(r'<enclosure[^>]*type="audio[^"]*"[^>]*url="([^"]+)"', block)
        # Prefer plain text; srt/vtt would need their own parser.
        tr = re.search(r'<podcast:transcript[^>]*url="([^"]+)"[^>]*type="text/plain"', block)
        out.append(Episode(
            guid=guid, show=show,
            title=_tag(block, "title"),
            published=_tag(block, "pubDate") or None,
            audio_url=audio.group(1) if audio else None,
            transcript_url=tr.group(1) if tr else None,
            description=(_tag(block, "description") or _tag(block, "itunes:summary"))[:4000],
        ))
    return out


def episode_mentions_subject(ep: Episode, alias_index: dict[str, list[str]]) -> set[str]:
    """Subjects named in the title/description — the free pre-filter.

    Loose on purpose: this decides only whether an episode is worth transcribing.
    Strict attribution happens later, in pipeline.transcript, with real context.
    """
    blob = f"{ep.title} {ep.description}".lower()
    hits = set()
    for key, aliases in alias_index.items():
        if any(re.search(rf"\b{re.escape(a)}\b", blob) for a in aliases):
            hits.add(key)
    return hits


def _transcribe(audio_url: str, *, model_size: str = WHISPER_MODEL, quiet: bool = False) -> list[Segment]:
    """Download audio and transcribe it. Lazy Whisper import — only this path needs it."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "faster-whisper is not installed — needed for shows that don't publish "
            "transcripts. Install with: pip install -r requirements-ingest.txt"
        ) from e

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "episode.mp3"
        data = _get(audio_url, timeout=300)
        if len(data) > MAX_AUDIO_MB * 1e6:
            raise RuntimeError(f"audio too large ({len(data)/1e6:.0f}MB > {MAX_AUDIO_MB}MB)")
        path.write_bytes(data)
        if not quiet:
            print(f"      transcribing {len(data)/1e6:.0f}MB with whisper '{model_size}'…")

        global _MODEL
        if _MODEL is None or _MODEL[0] != model_size:
            _MODEL = (model_size, WhisperModel(model_size, device="cpu", compute_type="int8"))
        segments, _info = _MODEL[1].transcribe(str(path), beam_size=1, vad_filter=True)
        return [Segment(start=s.start, end=s.end, text=s.text.strip()) for s in segments]


_MODEL: tuple[str, object] | None = None   # process-wide, loading it costs ~35s


def get_segments(ep: Episode, *, allow_whisper: bool = True, quiet: bool = False) -> list[Segment]:
    """Transcript segments for an episode: published text if offered, else Whisper."""
    if ep.transcript_url:
        try:
            raw = _get(ep.transcript_url, timeout=120).decode("utf-8", "ignore")
            segs = parse_published_transcript(raw)
            if segs:
                if not quiet:
                    print(f"      using published transcript ({len(segs)} turns, no compute)")
                return segs
        except Exception as e:
            if not quiet:
                print(f"      published transcript failed ({type(e).__name__}), falling back")
    if not allow_whisper:
        return []
    if not ep.audio_url:
        raise RuntimeError("episode has neither a transcript nor audio")
    return _transcribe(ep.audio_url, quiet=quiet)


def fetch_podcasts(alias_index: dict[str, list[str]], *, shows: list[str] | None = None,
                   seen_guids: set[str] | None = None, per_show: int = 20,
                   max_episodes: int = 5, allow_whisper: bool = True,
                   quiet: bool = False) -> tuple[list[dict], list[dict]]:
    """Ingest new episodes -> (passage records, per-episode outcomes).

    Records match the shape `ingestion.sources` produces, so everything downstream
    (stance scoring, embedding, storage, retrieval) is untouched. Outcomes are
    returned so the caller can record episodes it SKIPPED as well as ingested —
    otherwise a nightly job re-examines the same irrelevant episodes forever.

    `max_episodes` bounds a single run's transcription cost.
    """
    seen = seen_guids or set()
    shows = shows or DEFAULT_SHOWS
    records: list[dict] = []
    outcomes: list[dict] = []
    transcribed = 0

    def log(m):
        if not quiet:
            print(m)

    for show in shows:
        feed = discover_feed(show)
        if not feed:
            log(f"  {show}: feed not found, skipping")
            continue
        episodes = [e for e in list_episodes(feed, show, limit=per_show) if e.guid not in seen]
        log(f"  {show}: {len(episodes)} new episode(s)")

        for ep in episodes:
            base = {"guid": ep.guid, "show": show, "title": ep.title, "published": ep.published}
            subjects = episode_mentions_subject(ep, alias_index)
            if not subjects:
                outcomes.append({**base, "status": "skipped", "detail": "no covered subject in metadata"})
                continue
            if transcribed >= max_episodes:
                # Leave it unmarked so a later run picks it up.
                log(f"    (budget reached, leaving '{ep.title[:44]}' for next run)")
                continue

            log(f"    {ep.title[:60]}  ~{sorted(subjects)[:4]}")
            try:
                segs = get_segments(ep, allow_whisper=allow_whisper, quiet=quiet)
            except Exception as e:
                outcomes.append({**base, "status": "failed", "detail": f"{type(e).__name__}: {e}"})
                log(f"      ! {type(e).__name__}: {e}")
                continue
            if not segs:
                outcomes.append({**base, "status": "skipped", "detail": "no transcript available"})
                continue

            transcribed += 1
            passages = build_passages(segs, alias_index, episode={
                "guid": ep.guid, "show": show, "title": ep.title,
                "url": ep.audio_url, "published": ep.published,
            })
            log(f"      {len(segs)} segments -> {len(passages)} passages")
            records.extend(passages)
            outcomes.append({**base, "status": "ok", "n_passages": len(passages)})

    return records, outcomes
