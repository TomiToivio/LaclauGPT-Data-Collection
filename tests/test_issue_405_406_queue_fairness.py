"""The queue must not starve a kind, and a deferred job must not lose its turn (#405, #406).

Two symptoms, one seam. Eleven `web_source` rows sat at `attempts=0` for twelve days while six
account jobs were claimed every hour (#406); two P1 Bluesky sources were admitted in 1 and 3 of 16
cycles while their peers were admitted in 11-13 (#405). Both were invisible: the cycle reported
`ok` and `deferred_by_tick_limit: 0`.

The three properties pinned here:

* **claim order is deterministic** — the old key `(priority, created_at)` was a total tie in the
  live store (one bulk enqueue timestamp), so the order came from whichever index the planner
  picked. `(status, kind, ...)` sorts `bluesky_account` before `web_source`, every cycle, forever.
* **a kind cannot take every slot** — claims round-robin across kinds, so a starved stratum is
  reached on the next cycle rather than never.
* **a job deferred by the tick record limit is not a failure** — it gets its attempt refunded and
  keeps its place instead of being pushed a full `poll_seconds` back, which is what turned a
  capacity limit into a source's permanent cadence.
"""
from __future__ import annotations

import mongomock
import pytest

from laclaugpt_data_collection.distributed_jobs import (
    LASKIN_CAPABILITIES,
    NON_BROWSER_KINDS,
    PENDING,
    RUNNING,
    JobLeaseStore,
    dispatch_finish,
)


class Clock:
    def __init__(self, start: float = 1_793_205_466.1429622) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def store():
    collection = mongomock.MongoClient().db.jobs
    clock = Clock()
    s = JobLeaseStore(collection, clock=clock)
    s.ensure_indexes()
    return s, clock


def bulk(store, counts: dict[str, int], *, priority: int = 1) -> None:
    """Enqueue like the live store did: many rows, one clock read, so `created_at` ties exactly."""
    jobs = []
    for kind, n in counts.items():
        for i in range(n):
            jobs.append(
                {
                    "job_id": f"{kind}:{i}",
                    "kind": kind,
                    "name": f"{kind} {i}",
                    "priority": priority,
                }
            )
    store.enqueue(jobs)


def kinds_of(claimed):
    out = {}
    for doc in claimed:
        out[doc["kind"]] = out.get(doc["kind"], 0) + 1
    return out


def test_the_claim_order_is_not_decided_by_the_index_planner(store):
    """Two orders of insertion, one answer: `_id` ends the sort, so the plan cannot choose."""
    s, _ = store
    bulk(s, {"web_source": 3, "bluesky_account": 3})
    first = [d["_id"] for d in s.claim("w1", LASKIN_CAPABILITIES, limit=6, kinds=NON_BROWSER_KINDS)]

    collection = mongomock.MongoClient().db.jobs
    other = JobLeaseStore(collection, clock=Clock())
    other.ensure_indexes()
    bulk(other, {"bluesky_account": 3, "web_source": 3})
    second = [
        d["_id"] for d in other.claim("w1", LASKIN_CAPABILITIES, limit=6, kinds=NON_BROWSER_KINDS)
    ]

    assert first == second
    # Round-robin interleaves kinds on purpose — determinism is the property here, not global sort.


def test_a_kind_that_has_never_run_cannot_be_starved_by_a_bigger_kind(store):
    """The #406 shape: eleven web jobs behind eleven account jobs, six slots per cycle."""
    s, _ = store
    bulk(s, {"bluesky_account": 11, "web_source": 11})

    claimed = s.claim("laskin-cron", LASKIN_CAPABILITIES, limit=6, kinds=NON_BROWSER_KINDS)

    per_kind = kinds_of(claimed)
    assert len(claimed) == 6
    assert per_kind.get("web_source", 0) >= 1, per_kind
    assert per_kind.get("bluesky_account", 0) >= 1, per_kind
    # round-robin, not "whatever was left": no kind takes more than half the budget
    assert max(per_kind.values()) <= 3


def test_every_kind_is_reached_within_one_round_of_cycles(store):
    """Fairness over time: a source that waited gets a slot, without a reserved quota."""
    s, clock = store
    bulk(s, {"bluesky_account": 11, "web_source": 11, "scholarly_query": 2})
    seen: set[str] = set()
    for _ in range(4):
        claimed = s.claim("laskin-cron", LASKIN_CAPABILITIES, limit=6, kinds=NON_BROWSER_KINDS)
        for doc in claimed:
            seen.add(doc["kind"])
            s.complete(doc["_id"], "laskin-cron", outcome="ok")
        clock.advance(3600)

    assert seen == {"bluesky_account", "web_source", "scholarly_query"}


def test_never_run_jobs_are_claimed_before_jobs_whose_cadence_is_due(store):
    """`next_run_at` ascending with nulls first: the backlog is drained before the rotation."""
    s, clock = store
    bulk(s, {"bluesky_account": 2})
    first = s.claim("w", LASKIN_CAPABILITIES, limit=2, kinds=NON_BROWSER_KINDS)
    for doc in first:
        s.complete(doc["_id"], "w", outcome="ok")
    clock.advance(3600)

    s.enqueue([{"job_id": "web_source:new", "kind": "web_source", "name": "new", "priority": 1}])

    claimed = s.claim("w", LASKIN_CAPABILITIES, limit=3, kinds=NON_BROWSER_KINDS)
    assert [d["_id"] for d in claimed][0] == "web_source:new"


def test_claimable_by_kind_counts_what_the_worker_could_take(store):
    s, _ = store
    bulk(s, {"web_source": 11, "bluesky_account": 2, "x_account": 4})
    counts = s.claimable_by_kind(LASKIN_CAPABILITIES, kinds=NON_BROWSER_KINDS)
    assert counts == {"bluesky_account": 2, "web_source": 11}
    # a browser kind is not claimable by this worker, so it is not counted for it
    assert "x_account" not in counts


def test_a_deferred_job_keeps_its_turn_and_its_attempt(store):
    """#405's mechanism: `release()` charged a bounced job a full cadence and an attempt."""
    s, clock = store
    bulk(s, {"bluesky_account": 1})
    claimed = s.claim("w", LASKIN_CAPABILITIES, limit=1, kinds=NON_BROWSER_KINDS)
    job = claimed[0]
    assert job["attempts"] == 1
    before_next = job.get("next_run_at")

    assert s.defer(job["_id"], "w", reason="tick_record_limit") is True

    row = s.jobs.find_one({"_id": job["_id"]})
    assert row["status"] == PENDING
    assert row["attempts"] == 0, "a job that never started has not spent an attempt"
    assert row["next_run_at"] == before_next, "and it must not be pushed a cadence into the future"
    assert row["worker_id"] is None and row["lease_expires_at"] is None
    assert row["last_error"] == "tick_record_limit"

    # ...and it is still first in line on the same tick
    again = s.claim("w", LASKIN_CAPABILITIES, limit=1, kinds=NON_BROWSER_KINDS)
    assert again[0]["_id"] == job["_id"]


def test_dispatch_finish_defers_instead_of_releasing(store):
    """The cycle's own `tick_record_limit` outcome must take the deferral path."""
    s, _ = store
    bulk(s, {"bluesky_account": 1})
    claimed = s.claim("w", LASKIN_CAPABILITIES, limit=1, kinds=NON_BROWSER_KINDS)
    row = {**claimed[0], "name": "x"}

    dispatch_finish(
        s,
        {"_job_id": row["_id"], "name": "x"},
        {"status": "deferred", "reason": "tick_record_limit"},
        worker_id="w",
    )

    updated = s.jobs.find_one({"_id": row["_id"]})
    assert updated["status"] == PENDING
    assert updated["attempts"] == 0


def test_a_real_failure_still_burns_an_attempt_and_waits_for_the_cadence(store):
    """The deferral must not become a free retry loop for genuine failures."""
    s, clock = store
    bulk(s, {"bluesky_account": 1})
    claimed = s.claim("w", LASKIN_CAPABILITIES, limit=1, kinds=NON_BROWSER_KINDS)
    row = claimed[0]

    dispatch_finish(
        s,
        {"_job_id": row["_id"], "name": "x"},
        {"status": "error", "reason": "http 500"},
        worker_id="w",
    )

    updated = s.jobs.find_one({"_id": row["_id"]})
    assert updated["status"] == PENDING
    assert updated["attempts"] == 1
    assert updated["next_run_at"] == pytest.approx(row["next_run_at"] + 3600)


def test_claiming_marks_the_lease_so_another_worker_cannot_take_it(store):
    s, _ = store
    bulk(s, {"web_source": 2})
    taken = s.claim("w1", LASKIN_CAPABILITIES, limit=1, kinds=NON_BROWSER_KINDS)
    other = s.claim("w2", LASKIN_CAPABILITIES, limit=5, kinds=NON_BROWSER_KINDS)
    assert taken[0]["_id"] not in {d["_id"] for d in other}
    assert all(d["status"] == RUNNING for d in taken)


def test_a_released_source_waits_for_its_cadence(store):
    """The gate #407 caught: `release()` left a failed source PENDING with a future `next_run_at`,
    and the old claim ignored it, so "waits a cadence" was decoration."""
    s, clock = store
    bulk(s, {"bluesky_account": 1})
    claimed = s.claim("w", LASKIN_CAPABILITIES, limit=1, kinds=NON_BROWSER_KINDS)
    s.release(claimed[0]["_id"], "w", error="http 500")

    assert s.claim("w", LASKIN_CAPABILITIES, limit=1, kinds=NON_BROWSER_KINDS) == []
    assert s.claimable_by_kind(LASKIN_CAPABILITIES, kinds=NON_BROWSER_KINDS) == {}

    clock.advance(3601)
    assert [d["_id"] for d in s.claim("w", LASKIN_CAPABILITIES, limit=1, kinds=NON_BROWSER_KINDS)] == [
        claimed[0]["_id"]
    ]


def test_a_deferred_job_is_still_claimable_on_the_same_tick(store):
    """The gate must not re-create #405: a deferral keeps `next_run_at` in the past, so the job
    stays due and keeps its place in line."""
    s, _ = store
    bulk(s, {"web_source": 2})
    taken = s.claim("w", LASKIN_CAPABILITIES, limit=2, kinds=NON_BROWSER_KINDS)
    for doc in taken:
        s.defer(doc["_id"], "w")
    assert s.claimable_by_kind(LASKIN_CAPABILITIES, kinds=NON_BROWSER_KINDS) == {"web_source": 2}
    assert len(s.claim("w", LASKIN_CAPABILITIES, limit=2, kinds=NON_BROWSER_KINDS)) == 2
