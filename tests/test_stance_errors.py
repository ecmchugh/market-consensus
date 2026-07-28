"""A broken pipeline must never look like a quiet corpus.

Regression test for the bug the 2026-07-28 seed run exposed: every exception in
`_score_one` was swallowed into `None`, which the caller reads as "irrelevant". When
the Anthropic balance hit zero, every item was dropped, `volume` came back 0, and
both the seed's coverage report and the live UI said "No discussion found" — a
billing failure wearing a coverage result's clothes.

Hermetic: the Anthropic client is a stub, so nothing here touches the network.
"""
import sys
import types

import anthropic
import httpx

from pipeline import stance

ok = True


def check(label, cond, extra=""):
    global ok
    ok = ok and cond
    print(f"{'PASS' if cond else 'FAIL'}  {label}{(' — ' + extra) if extra else ''}")


def _resp(status):
    return httpx.Response(status, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


def _err(cls, status, msg):
    return cls(msg, response=_resp(status), body=None)


CREDIT_ERROR = _err(anthropic.BadRequestError, 400, "Your credit balance is too low")
AUTH_ERROR = _err(anthropic.AuthenticationError, 401, "invalid x-api-key")
RATE_ERROR = _err(anthropic.RateLimitError, 429, "rate limited")


class StubClient:
    """Anthropic client stand-in. `behavior(i)` returns a JSON body or raises."""

    def __init__(self, behavior):
        self.messages = types.SimpleNamespace(create=self._create)
        self._behavior = behavior
        self._i = 0

    def _create(self, **_kw):
        i, self._i = self._i, self._i + 1
        out = self._behavior(i)
        if isinstance(out, Exception):
            raise out
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=out)])


def records(n):
    return [{"title": f"t{i}", "text": f"body {i}", "url": f"u{i}"} for i in range(n)]


def run(behavior, n=20, workers=4):
    """Patch Anthropic to yield our stub, then score."""
    real = anthropic.Anthropic
    anthropic.Anthropic = lambda *a, **k: StubClient(behavior)
    # score_stance imports Anthropic inside the function body, so patching the
    # module attribute is enough.
    try:
        return stance.score_stance(records(n), "TestSubject", max_workers=workers, quiet=True)
    finally:
        anthropic.Anthropic = real


# The real call prefills an opening "{" and the model completes the object, so the
# response text ENDS with the closing brace. `_score_one` does json.loads("{" + text),
# so these fixtures must include it — without it every fixture is a parse error and
# the happy-path tests pass vacuously.
RELEVANT = '"relevant": true, "score": 42, "rationale": "bullish"}'
IRRELEVANT = '"relevant": false, "score": 0, "rationale": "off topic"}'

# --- the actual regression: billing/auth failure must RAISE, not return [] ---
for label, exc in (("credit exhausted", CREDIT_ERROR), ("bad api key", AUTH_ERROR)):
    try:
        got = run(lambda i: exc)
        check(f"{label} raises (not silent empty)", False, f"returned {len(got)} items")
    except stance.StanceScoringError as e:
        check(f"{label} raises StanceScoringError", True)
        check(f"{label} message names the cause", "credit" in str(e).lower() or "api-key" in str(e).lower(), str(e)[:90])

# --- genuine irrelevance is still an empty list, NOT an error ---------------
try:
    got = run(lambda i: IRRELEVANT)
    check("all-irrelevant returns [] without raising", got == [], f"{len(got)} items")
except stance.StanceScoringError as e:
    check("all-irrelevant returns [] without raising", False, str(e)[:90])

# --- happy path ------------------------------------------------------------
try:
    got = run(lambda i: RELEVANT)
    check("all-relevant returns every item", len(got) == 20, f"{len(got)}/20")
    check("scores are parsed", bool(got) and all(r["score"] == 42 for r in got))
except stance.StanceScoringError as e:
    check("all-relevant returns every item", False, str(e)[:90])

# --- a few scattered failures are tolerated --------------------------------
# 2/20 = 10%, under MAX_ERROR_RATE. Those items drop; the rest survive.
try:
    got = run(lambda i: RATE_ERROR if i in (0, 1) else RELEVANT, n=20)
    check("a few transient failures are tolerated", len(got) >= 17, f"kept {len(got)}/20")
except stance.StanceScoringError as e:
    check("a few transient failures are tolerated", False, str(e)[:90])

# --- but a mostly-failing batch must not be reported as thin coverage ------
try:
    got = run(lambda i: RATE_ERROR, n=20)
    check("mostly-failing batch raises", False, f"returned {len(got)} items")
except stance.StanceScoringError as e:
    check("mostly-failing batch raises", True)
    check("message refuses the low-coverage reading", "coverage" in str(e).lower(), str(e)[:90])

# --- unparseable model output is still just a dropped item -----------------
try:
    got = run(lambda i: "this is not json at all", n=8)
    check("garbage model output drops the item, no raise", got == [], f"{len(got)} items")
except stance.StanceScoringError as e:
    check("garbage model output drops the item, no raise", False, str(e)[:90])

# --- 429 must not be classified fatal (it is retryable) --------------------
check("429 is not fatal", stance._is_fatal(RATE_ERROR) is False)
check("400 is fatal", stance._is_fatal(CREDIT_ERROR) is True)
check("401 is fatal", stance._is_fatal(AUTH_ERROR) is True)

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
