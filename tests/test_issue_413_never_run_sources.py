"""A newly added source must run, and the tail of the list must not starve (#413).

The Denmark row was added to the manifest on 2026-11-12, appeared in the drift check and in the
source-budget caps, had a `pending` job row with `attempts: 0` — and produced **0 records in 24 h**
while 18–23 jobs sat claimable-but-unclaimed every cycle. The row was not broken; the *claim order*
was. Priority first, then a schedule that every long-standing P1 job carries, means a P2 row added
yesterday sorts behind every P1 row forever, and the tier refills hourly.

Two properties, and a third that is honesty about capacity:

* the stalest claimable job is served **first**, regardless of priority, so a newly added source runs
  within a cycle or two;
* within the rest of the budget, the kind round-robin from #405/#406 still holds;
* a run that cannot serve everything still says so — `claimable_by_kind` exists for that, and the
  cycle record now also counts the never-claimed rows.
"""
from __future__ import annotations

import mongomock
import pytest

from laclaugpt_data_collection.distributed_jobs import (
    LASKIN_CAPABILITIES,
    NON_BROWSER_KINDS,
    JobLeaseStore,
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


def enqueue(store, rows):
    store.enqueue(rows)


def aged_p1_sources(store, clock, count: int = 12, cycles: int = 2) -> None:
    """Long-standing P1 rows that have run and been re-armed: the shape that starved the tail."""
    enqueue(
        store,
        [
            {"job_id": f"bluesky_account:p1-{i}", "kind": "bluesky_account", "name": f"P1 {i}", "priority": 1}
            for i in range(count)
        ],
    )
    for _ in range(cycles):
        for doc in store.claim("w", LASKIN_CAPABILITIES, limit=6, kinds=NON_BROWSER_KINDS):
            store.complete(doc["_id"], "w", outcome="ok")
        clock.advance(3600)
        store.rearm_due()


def test_a_new_lower_priority_source_is_claimed_though_p1_rows_are_pending(store):
    """The defect, inverted: Denmark is P2, never claimed, and still gets a slot."""
    s, clock = store
    aged_p1_sources(s, clock)
    enqueue(s, [{"job_id": "bluesky_account:denmark", "kind": "bluesky_account", "name": "Folkebevægelsen", "priority": 2}])

    claimed = s.claim("laskin-cron", LASKIN_CAPABILITIES, limit=6, kinds=NON_BROWSER_KINDS)

    ids = [doc["_id"] for doc in claimed]
    assert "bluesky_account:denmark" in ids, ids
    assert len(claimed) == 6, "the rest of the budget is still spent on the priority order"


def test_without_the_starvation_pass_the_new_source_is_not_reached(store):
    """`starvation_slots=0` reproduces the old behaviour, which is what makes the fix a fix."""
    s, clock = store
    aged_p1_sources(s, clock)
    enqueue(s, [{"job_id": "bluesky_account:denmark", "kind": "bluesky_account", "name": "Folkebevægelsen", "priority": 2}])

    claimed = s.claim("laskin-cron", LASKIN_CAPABILITIES, limit=6, kinds=NON_BROWSER_KINDS, starvation_slots=0)

    assert "bluesky_account:denmark" not in [doc["_id"] for doc in claimed]


def test_a_just_added_source_is_served_before_older_never_run_rows(store):
    """Among never-run rows the newest addition wins: it is the operator's most recent decision."""
    s, clock = store
    enqueue(s, [{"job_id": "bluesky_account:older", "kind": "bluesky_account", "name": "older", "priority": 1}])
    clock.advance(600)
    enqueue(s, [{"job_id": "bluesky_account:newer", "kind": "bluesky_account", "name": "newer", "priority": 2}])

    first = s.claim("w", LASKIN_CAPABILITIES, limit=1, kinds=NON_BROWSER_KINDS, starvation_slots=1)
    assert first[0]["_id"] == "bluesky_account:newer"

    s.complete("bluesky_account:newer", "w", outcome="ok")
    second = s.claim("w", LASKIN_CAPABILITIES, limit=1, kinds=NON_BROWSER_KINDS, starvation_slots=1)
    assert second[0]["_id"] == "bluesky_account:older", "the one just served is not served again first"


def test_among_rows_that_have_run_the_longest_wait_wins(store):
    """Priority is not the age: a P1 row served a minute ago must yield to a P2 row served an hour ago."""
    s, clock = store
    enqueue(
        s,
        [
            {"job_id": "bluesky_account:p1", "kind": "bluesky_account", "name": "p1", "priority": 1},
            {"job_id": "bluesky_account:p2", "kind": "bluesky_account", "name": "p2", "priority": 2},
        ],
    )
    clock.advance(3600)
    s.jobs.update_one({"_id": "bluesky_account:p2"}, {"$set": {"last_claimed_at": clock.now - 3600}})
    clock.advance(60)
    s.jobs.update_one({"_id": "bluesky_account:p1"}, {"$set": {"last_claimed_at": clock.now - 60}})

    claimed = s.claim("w", LASKIN_CAPABILITIES, limit=1, kinds=NON_BROWSER_KINDS, starvation_slots=1)
    assert claimed[0]["_id"] == "bluesky_account:p2"


def test_claiming_records_when_the_job_last_ran(store):
    """Fairness needs an age per job; `next_run_at` was a schedule, not an age."""
    s, _ = store
    enqueue(s, [{"job_id": "bluesky_account:a", "kind": "bluesky_account", "name": "a", "priority": 1}])
    claimed = s.claim("w", LASKIN_CAPABILITIES, limit=1, kinds=NON_BROWSER_KINDS)
    assert claimed[0]["last_claimed_at"] == pytest.approx(1_793_205_466.1429622)


def test_the_reserve_is_a_third_of_the_budget_and_never_exceeds_it(store):
    s, _ = store
    enqueue(
        s,
        [
            {"job_id": f"web_source:{i}", "kind": "web_source", "name": str(i), "priority": 1}
            for i in range(9)
        ],
    )
    assert len(s.claim("w", LASKIN_CAPABILITIES, limit=3, kinds=NON_BROWSER_KINDS)) == 3
    # limit 1 still yields one job; a reserve larger than the budget is clamped, not a crash
    s2 = JobLeaseStore(mongomock.MongoClient().db.jobs, clock=Clock())
    s2.ensure_indexes()
    enqueue(s2, [{"job_id": f"web_source:{i}", "kind": "web_source", "name": str(i), "priority": 1} for i in range(3)])
    assert len(s2.claim("w", LASKIN_CAPABILITIES, limit=1, kinds=NON_BROWSER_KINDS, starvation_slots=5)) == 1


def test_the_tail_of_a_large_queue_is_reached_within_a_few_cycles(store):
    """The invariant that matters: every claimable source is served, and none waits unbounded."""
    s, clock = store
    enqueue(
        s,
        [
            {"job_id": f"bluesky_account:{i:02d}", "kind": "bluesky_account", "name": str(i), "priority": 1 if i < 12 else 2}
            for i in range(20)
        ],
    )
    served: set[str] = set()
    for _ in range(8):
        for doc in s.claim("w", LASKIN_CAPABILITIES, limit=6, kinds=NON_BROWSER_KINDS):
            served.add(doc["_id"])
            s.complete(doc["_id"], "w", outcome="ok")
        clock.advance(3600)

    assert len(served) == 20, f"only {len(served)} of 20 sources were ever served"


def test_an_empty_queue_is_not_an_error(store):
    s, _ = store
    assert s.claim("w", LASKIN_CAPABILITIES, limit=6, kinds=NON_BROWSER_KINDS) == []
