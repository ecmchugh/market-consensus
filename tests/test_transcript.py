"""Entity disambiguation and passage attribution for podcast transcripts.

Every case here is a failure observed in a REAL transcript during the spike, not a
hypothetical. Hermetic — no network, no API, no audio.

    PYTHONPATH=. python tests/test_transcript.py
"""
import sys

from pipeline.transcript import (
    Segment, build_alias_index, build_passages, count_subjects, find_subjects,
    parse_published_transcript,
)

ok = True


def check(label, cond, extra=""):
    global ok
    ok = ok and cond
    print(f"{'PASS' if cond else 'FAIL'}  {label}{(' — ' + extra) if extra else ''}")


# Shaped like the resolver's real output, including the junk aliases it emits.
RESOLVED = {
    "NVDA": {"display": "Nvidia", "aliases": ["NVDA", "Jensen Huang"]},
    "INTC": {"display": "Intel", "aliases": ["INTC", "Intel Corporation"]},
    "AAPL": {"display": "Apple", "aliases": ["AAPL", "Apple Inc."]},
    "META": {"display": "Meta Platforms", "aliases": ["Facebook", "META"]},
    "ARM": {"display": "Arm Holdings", "aliases": ["Arm Holdings plc", "ARM stock"]},
    "AMD": {"display": "AMD", "aliases": ["Advanced Micro Devices", "NVDA competitor"]},
    "TSM": {"display": "TSMC", "aliases": ["Taiwan Semiconductor"]},
    "BTC-USD": {"display": "Bitcoin", "aliases": ["BTC", "digital gold", "crypto"]},
}
IDX = build_alias_index(RESOLVED)

# --- the alias index must reject the resolver's unusable aliases --------------
check("drops over-broad alias 'crypto'", "crypto" not in IDX.get("BTC-USD", []), str(IDX.get("BTC-USD")))
check("keeps real name 'bitcoin'", "bitcoin" in IDX.get("BTC-USD", []))
check("drops description 'nvda competitor'", "nvda competitor" not in IDX.get("AMD", []), str(IDX.get("AMD")))
check("strips corporate suffixes", "apple" in IDX.get("AAPL", []), str(IDX.get("AAPL")))

# --- disambiguation: the exact strings that broke naive matching --------------
NEGATIVE = [
    ("the intelligence actually becomes useful in practical ways", "INTC"),
    ("I ate an apple for breakfast before going on a long walk", "AAPL"),
    ("he kept the deal at arm's length for obvious legal reasons", "ARM"),
    ("a meta-analysis of the clinical trial data showed no effect", "META"),
]
for text, key in NEGATIVE:
    check(f"rejects {key} in {text[:38]!r}", key not in find_subjects(text, IDX))

POSITIVE = [
    ("Intel's earnings were terrible and the stock is down 12% this quarter", "INTC"),
    ("Apple's market cap and earnings guidance badly disappointed investors", "AAPL"),
    ("Nvidia shares ripped after that revenue guidance, huge quarter", "NVDA"),
]
for text, key in POSITIVE:
    check(f"detects {key} in {text[:38]!r}", key in find_subjects(text, IDX))

# --- counting drives attribution ---------------------------------------------
listy = "the top 30 US listed chips, people like Nvidia, TSMC, AMD, all those big names"
c = count_subjects(listy, IDX)
check("counts each listed name once", all(v == 1 for v in c.values()), str(c))

discussed = ("Nvidia is the whole trade here. Nvidia's margins are the tell, and if Nvidia "
             "guides down next quarter the entire AI complex reprices. TSMC matters too.")
c2 = count_subjects(discussed, IDX)
check("counts a discussed subject repeatedly", c2.get("NVDA", 0) >= 3, str(c2))

# --- THE REGRESSION: one sentence must not become three opinions -------------
# Real text from the All-In episode. It named Nvidia, TSMC and AMD once each and was
# previously emitted three times, inflating volume and correlating the three subjects.
segs = [
    Segment(0, 5, "How did this all blow up? Well, NASDAQ's chip index,"),
    Segment(5, 10, "the Philadelphia Semiconductor Index, is down over 20% this month."),
    Segment(10, 15, "That's bear market territory for those who don't play in the markets."),
    Segment(15, 20, "The index includes the top 30 US listed chips, that's people like"),
    Segment(20, 25, "Nvidia, TSMC, AMD, you know all those big names, but it bounced back today."),
    Segment(25, 30, "Traders were caught badly offside on leverage into that drawdown."),
]
ps = build_passages(segs, IDX, episode={"guid": "t1", "show": "test"})
subj = [p["subject"] for p in ps]
texts = {p["text"] for p in ps}
check("list mention yields ONE subject, not three", len(subj) <= 1, f"got {subj}")
check("no duplicated passage text", len(texts) == len(ps), f"{len(ps)} passages, {len(texts)} distinct")

# A genuinely two-subject passage should still produce both.
segs2 = [
    Segment(0, 5, "Nvidia is expensive here and Nvidia's guidance looks stretched to me."),
    Segment(5, 10, "Meanwhile Intel is cheap, Intel has real capacity, and Intel's floor is"),
    Segment(10, 15, "much higher than people think given the foundry earnings and revenue."),
    Segment(15, 20, "So I'd be short the first name and long the second one into the quarter."),
]
ps2 = build_passages(segs2, IDX, episode={"guid": "t2", "show": "test"})
check("two genuinely-discussed subjects both emit", {"NVDA", "INTC"} <= {p["subject"] for p in ps2},
      str({p["subject"] for p in ps2}))

# --- passages must be big enough to carry a stance ---------------------------
check("passages exceed the fragment size that broke scoring",
      all(len(p["text"].split()) >= 25 for p in ps2), str([len(p["text"].split()) for p in ps2]))

# --- published (diarized) transcript parsing ---------------------------------
RAW = """00:00:02
Speaker 1: Bloomberg Audio Studios, Podcasts, radio News.

00:00:18
Speaker 2: Hello and welcome to another episode of the podcast.

00:00:33
Speaker 3: Nvidia earnings are the only thing that matters for this market right now.
"""
segs3 = parse_published_transcript(RAW)
check("parses diarized transcript", len(segs3) == 3, f"{len(segs3)} segments")
check("extracts speakers", [s.speaker for s in segs3] == ["Speaker 1", "Speaker 2", "Speaker 3"],
      str([s.speaker for s in segs3]))
check("parses timestamps to seconds", [s.start for s in segs3] == [2, 18, 33], str([s.start for s in segs3]))

# --- records match the shape the rest of the pipeline expects ----------------
if ps2:
    r = ps2[0]
    check("record has the ingestion contract fields",
          all(k in r for k in ("external_id", "source", "source_type", "subject", "text", "url", "timestamp")),
          str(sorted(r)))
    check("source_type marks podcasts as their own population", r["source_type"] == "podcast")

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
