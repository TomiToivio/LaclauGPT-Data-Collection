"""Regression tests for unclaimed P2 sources behind recurring P1 polls (#413).

The queue rotates across source kinds, but each kind also needs fairness across
priorities. Otherwise a P2 Bluesky row may remain attempts=0 for days even
though hourly P1 accounts repeatedly finish and become eligible again.
"""
from __future__ import annotations

import mongomock

from laclaugpt_data_collection.distributed_jobs import (
    LASKIN_CAPABILITIES,
    NON_BROWSER_KINDS,
    JobLeaseStore,
    dispatch_claim,
    dispatch_finish,
)


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_never_claimed_p2_beats_due_recurring_p1_same_kind():
    clock = Clock()
    store = JobLeaseStore(mongomock.MongoClient().db.jobs, clock=clock)
    source_rows = [
        {"kind": "bluesky_account", "name": f"lab-{i}", "priority": "P1"}
        for i in range(6)
    ]
    first = dispatch_claim(store, source_rows, worker_id="laskin", max_jobs=6,
                           capabilities=LASKIN_CAPABILITIES, executable_kinds=NON_BROWSER_KINDS)
    for row in first:
        dispatch_finish(store, row, {"status": "ok"}, worker_id="laskin")

    # A new Danish grassroots source is added after the priority-one sources
    # ran. It is eligible before their next one-hour poll.
    clock.advance(60)
    danish = {"kind": "bluesky_account", "name": "Folkebevægelsen Stop datacentre (Denmark)",
              "handle": "stopdatacentre.dk", "priority": "P2"}
    source_rows.append(danish)
    store.enqueue([{**danish, "job_id": "bluesky_account:" + danish["name"]}])
    clock.advance(3600)
    store.rearm_due()

    claimed = dispatch_claim(store, source_rows, worker_id="laskin", max_jobs=1,
                             capabilities=LASKIN_CAPABILITIES, executable_kinds=NON_BROWSER_KINDS)
    assert [row["name"] for row in claimed] == [danish["name"]]
    assert store.jobs.find_one({"_id": "bluesky_account:" + danish["name"]})["attempts"] == 1


def test_backlogged_p2_bluesky_accounts_are_all_attempted_within_bounded_cycles():
    clock = Clock()
    store = JobLeaseStore(mongomock.MongoClient().db.jobs, clock=clock)
    sources = [
        {"kind": "bluesky_account", "name": f"P1-{i}", "priority": "P1"}
        for i in range(6)
    ]
    first = dispatch_claim(store, sources, worker_id="laskin", max_jobs=6)
    for row in first:
        dispatch_finish(store, row, {"status": "ok"}, worker_id="laskin")

    clock.advance(60)
    p2_sources = [
        {"kind": "bluesky_account", "name": name, "priority": "P2"}
        for name in ("METR", "Ethan Mollick", "No Desert Data Center Coalition",
                     "Folkebevægelsen Stop datacentre (Denmark)")
    ]
    sources.extend(p2_sources)
    seen = set()
    # Six older due P1 jobs consume the first three two-slot cycles;
    # all four newly enrolled P2 accounts are admitted within five cycles.
    for _ in range(5):
        clock.advance(3600)
        claimed = dispatch_claim(store, sources, worker_id="laskin", max_jobs=2)
        for row in claimed:
            seen.add(row["name"])
            dispatch_finish(store, row, {"status": "ok"}, worker_id="laskin")

    assert {row["name"] for row in p2_sources} <= seen


def test_equal_due_times_keep_priority_and_deterministic_identity_order():
    clock = Clock()
    store = JobLeaseStore(mongomock.MongoClient().db.jobs, clock=clock)
    store.enqueue([
        {"job_id": "bluesky_account:z", "kind": "bluesky_account", "priority": "P2"},
        {"job_id": "bluesky_account:b", "kind": "bluesky_account", "priority": "P1"},
        {"job_id": "bluesky_account:a", "kind": "bluesky_account", "priority": "P1"},
    ])
    claimed = store.claim("laskin", LASKIN_CAPABILITIES, limit=3)
    assert [row["_id"] for row in claimed] == [
        "bluesky_account:a", "bluesky_account:b", "bluesky_account:z"
    ]
