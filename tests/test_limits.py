"""Verify the API spend/abuse guards. HERMETIC — never reaches a real cold run.

Earlier version of this file drove the budget test through the live endpoint with a
real uncached subject. When the precondition didn't hold, the request fell through
to an actual paid pipeline run. Everything that could reach `run_query` is now
stubbed, so a failing assertion costs nothing.
"""
import os

os.environ["CONSENSUS_DB"] = "demo_corpus.db"
os.environ["QUERY_RATE_LIMIT"] = "3"
os.environ["QUERY_RATE_WINDOW_S"] = "3600"

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api import limits, main  # noqa: E402
from pipeline.itemstore import get_store  # noqa: E402

client = TestClient(main.app)
ok = True


def check(label, cond, extra=""):
    global ok
    ok = ok and cond
    print(f"{'PASS' if cond else 'FAIL'}  {label}{(' — ' + extra) if extra else ''}")


class StubStore:
    """Store whose reading count we control exactly."""

    def __init__(self, count):
        self._count = count

    def count_readings_since(self, _since):
        return self._count


class CountlessStore:
    """A backend that predates count_readings_since — must fail open, not crash."""

    def count_readings_since(self, _since):
        raise NotImplementedError


# --- the real counter the budget is built on ------------------------------
store = get_store()
today = store.count_readings_since(limits.utc_day_start())
check("count_readings_since returns an int", isinstance(today, int), f"{today} today")
check("count_readings_since(future) == 0", store.count_readings_since("2999-01-01T00:00:00+00:00") == 0)
check("day boundary is UTC midnight", limits.utc_day_start().endswith("T00:00:00+00:00"))

# --- budget unit behavior, no network -------------------------------------
limits.DAILY_COLD_QUERY_BUDGET = 10
try:
    limits.enforce_daily_budget(StubStore(9))
    check("under budget passes", True)
except HTTPException:
    check("under budget passes", False)

for n, label in ((10, "at budget blocks"), (99, "over budget blocks")):
    try:
        limits.enforce_daily_budget(StubStore(n))
        check(label, False)
    except HTTPException as e:
        check(label, e.status_code == 503 and "budget" in e.detail.lower(), f"{e.status_code}")

limits.DAILY_COLD_QUERY_BUDGET = 0
try:
    limits.enforce_daily_budget(StubStore(10_000))
    check("budget of 0 disables the cap", True)
except HTTPException:
    check("budget of 0 disables the cap", False)

limits.DAILY_COLD_QUERY_BUDGET = 10
try:
    limits.enforce_daily_budget(CountlessStore())
    check("store without counter fails open (warns, doesn't crash)", True)
except HTTPException:
    check("store without counter fails open (warns, doesn't crash)", False)

# --- endpoint returns 503 before doing any paid work ----------------------
# get_store is stubbed over budget AND run_query is replaced with a tripwire, so if
# the guard ever failed to fire this reports it instead of spending money.
reached = {"paid": False}


def tripwire(*a, **k):
    reached["paid"] = True
    return {"subject": "X", "is_financial": True}


orig_store, orig_run = main.get_store, main.query.run_query
main.get_store = lambda: StubStore(10_000)
main.query.run_query = tripwire
limits._query_limiter = limits.SlidingWindowLimiter(50, 3600)
try:
    r = client.post("/subjects/query", json={"subject": "some uncached subject"})
    check("cold query blocked by budget (503)", r.status_code == 503, f"got {r.status_code}")
    check("paid path never reached", reached["paid"] is False)
finally:
    main.get_store, main.query.run_query = orig_store, orig_run

# --- cached path is free: served even with the budget fully exhausted -----
# get_fresh_cached is stubbed rather than leaning on a real row in demo_corpus.db:
# readings expire after 24h, so a DB-backed version of this assertion passes or
# fails depending on how recently someone ran a query. Flaky tests get ignored.
FAKE_CACHED = {"subject": "NVDA", "display": "Nvidia", "is_financial": True,
               "consensus_score": 7.3, "volume": 106, "cached": True}
orig_fresh = main.query.get_fresh_cached
main.get_store = lambda: StubStore(10_000)
main.query.get_fresh_cached = lambda *a, **k: dict(FAKE_CACHED)
try:
    r = client.post("/subjects/query", json={"subject": "Nvidia"})
    check("cached query 200 despite exhausted budget", r.status_code == 200, f"got {r.status_code}")
    check("cached response flagged cached", r.status_code == 200 and r.json().get("cached") is True)
finally:
    main.get_store, main.query.get_fresh_cached = orig_store, orig_fresh

# --- per-IP rate limit ----------------------------------------------------
# Same reasoning as above: serve a stub cached reading so this measures the limiter
# rather than the age of whatever is in the DB.
main.query.get_fresh_cached = lambda *a, **k: dict(FAKE_CACHED)
limits._query_limiter = limits.SlidingWindowLimiter(3, 3600)
codes = [client.post("/subjects/query", json={"subject": "Nvidia"}).status_code for _ in range(5)]
check("rate limit trips after exactly 3", codes[:3] == [200, 200, 200] and codes[3] == 429, f"codes={codes}")
r429 = client.post("/subjects/query", json={"subject": "Nvidia"})
check("429 carries Retry-After", "retry-after" in {k.lower() for k in r429.headers})
check("limiter of 0 disables", limits.SlidingWindowLimiter(0, 3600).check("x") is None)
check("limiter isolates by key", limits.SlidingWindowLimiter(1, 3600).check("other-ip") is None)

# --- CORS is closed by default -------------------------------------------
check("CORS not wildcard", "*" not in main.ALLOWED_ORIGINS, str(main.ALLOWED_ORIGINS))
check("CORS allows dev origin", "http://localhost:5173" in main.ALLOWED_ORIGINS)

# --- reads unaffected -----------------------------------------------------
check("GET latest 200", client.get("/subjects/NVDA/latest").status_code == 200)
check("GET history 200", client.get("/subjects/NVDA/history").status_code == 200)
check("health 200", client.get("/health").status_code == 200)

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
raise SystemExit(0 if ok else 1)
