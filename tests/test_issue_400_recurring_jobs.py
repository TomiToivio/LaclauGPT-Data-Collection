"""#400: a manifest row is a source that is polled, not a task that runs once.

The failure this file pins down: every non-browser source completed exactly once over four and a
half days, after which the queue held 0 pending jobs, no code path could make them claimable again,
and the collector logged ``status: ok`` for fourteen consecutive cycles while collecting nothing.

These run against mongomock because the fix lives in Mongo update semantics — a hand-written fake
would test the fake.
"""
from __future__ import annotations

import mongomock
import pytest

from laclaugpt_data_collection.distributed_jobs import (
    CANCELLED,
    DEFAULT_POLL_SECONDS,
    DONE,
    FAILED,
    LASKIN_CAPABILITIES,
    PENDING,
    JobLeaseStore,
    dispatch_claim,
    job_identity,
    poll_seconds_for,
)


class Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def store() -> JobLeaseStore:
    s = JobLeaseStore(mongomock.MongoClient().db.jobs, clock=Clock())
    s.ensure_indexes()
    return s


def rows(*specs):
    out = []
    for spec in specs:
        kind, name = spec[0], spec[1]
        extra = spec[2] if len(spec) > 2 else {}
        out.append({"kind": kind, "name": name, "priority": 2,
                    "job_id": f"{kind}:{name}", **extra})
    return out


def finish(store: JobLeaseStore, worker: str = "laskin", limit: int = 10):
    claimed = store.claim(worker, LASKIN_CAPABILITIES, limit=limit)
    for job in claimed:
        store.complete(job["_id"], worker)
    return claimed


def test_the_default_cadence_reproduces_the_hourly_cycle():
    assert poll_seconds_for({"kind": "web_source", "name": "x"}) == DEFAULT_POLL_SECONDS


def test_a_row_may_override_its_cadence():
    assert poll_seconds_for({"kind": "web_source", "name": "x", "poll_minutes": 15}) == 900
    assert poll_seconds_for({"kind": "web_source", "name": "x", "poll_minutes": 0}) == 0


def test_a_completed_job_becomes_claimable_again_when_its_cadence_elapses(store):
    store.enqueue(rows(("web_source", "yle")))
    assert [c["_id"] for c in finish(store)] == ["web_source:yle"]

    # Immediately after completion the queue is empty — that part is correct.
    assert store.claim("laskin", LASKIN_CAPABILITIES, limit=10) == []

    store._clock.advance(DEFAULT_POLL_SECONDS + 1)
    assert store.rearm_due() == 1
    assert [c["_id"] for c in store.claim("laskin", LASKIN_CAPABILITIES, limit=10)] == ["web_source:yle"]


def test_a_job_finished_before_the_field_existed_is_still_due(store):
    """The migration case that made the fix inert in production on its first run.

    The 01:10 cycle wrote ``poll_seconds`` onto every existing job but not ``next_run_at`` (that
    field is insert-only by design). A filter of ``next_run_at <= now`` therefore matched nothing,
    the queue stayed at zero pending, and the sources stayed stopped — the original bug, wearing a
    migration.
    """
    store.enqueue(rows(("web_source", "yle")))
    store.jobs.update_one({"_id": "web_source:yle"},
                          {"$set": {"status": DONE}, "$unset": {"next_run_at": ""}})
    assert store.jobs.find_one({"_id": "web_source:yle"}).get("next_run_at") is None

    assert store.rearm_due() == 1
    assert store.jobs.find_one({"_id": "web_source:yle"})["status"] == PENDING


def test_a_job_not_yet_due_is_not_rearmed(store):
    store.enqueue(rows(("web_source", "yle", {"poll_minutes": 240})))
    finish(store)
    store._clock.advance(3600)
    assert store.rearm_due() == 0
    assert store.claim("laskin", LASKIN_CAPABILITIES, limit=10) == []


def test_rearming_restores_a_fresh_attempt_budget(store):
    """A transient outage must not end a source: three failures then quiet forever is the bug."""
    store.enqueue(rows(("web_source", "yle", {"max_attempts": 1})))
    claimed = store.claim("laskin", LASKIN_CAPABILITIES, limit=1)
    store.release(claimed[0]["_id"], "laskin", error="network down")
    assert store.jobs.find_one({"_id": "web_source:yle"})["status"] == FAILED

    store._clock.advance(DEFAULT_POLL_SECONDS + 1)
    assert store.rearm_due() == 1
    doc = store.jobs.find_one({"_id": "web_source:yle"})
    assert doc["status"] == PENDING
    assert doc["attempts"] == 0


def test_one_shot_rows_never_rearm(store):
    store.enqueue(rows(("web_source", "once", {"poll_minutes": 0})))
    finish(store)
    store._clock.advance(10 * DEFAULT_POLL_SECONDS)
    assert store.rearm_due() == 0


def test_a_deactivated_manifest_row_does_not_stay_claimable(store):
    """The six deactivated scholarly queries kept being claimed for two hours (#400)."""
    store.enqueue(rows(("scholarly_query", "old"), ("web_source", "live")))
    store.cancel_missing([job_identity({"kind": "web_source", "name": "live"})])
    doc = store.jobs.find_one({"_id": "scholarly_query:old"})
    assert doc["status"] == CANCELLED
    assert [c["_id"] for c in store.claim("laskin", LASKIN_CAPABILITIES, limit=10)] == ["web_source:live"]


def test_a_cancelled_job_is_not_rearmed_even_when_overdue(store):
    store.enqueue(rows(("scholarly_query", "old")))
    store.cancel_missing([])
    store._clock.advance(10 * DEFAULT_POLL_SECONDS)
    assert store.rearm_due() == 0


def test_completing_a_recurring_job_records_when_it_runs_next(store):
    store.enqueue(rows(("web_source", "yle", {"poll_minutes": 30})))
    claimed = store.claim("laskin", LASKIN_CAPABILITIES, limit=1)
    store.complete(claimed[0]["_id"], "laskin")
    doc = store.jobs.find_one({"_id": "web_source:yle"})
    assert doc["next_run_at"] == doc["updated_at"] + 1800


def test_re_reading_the_manifest_does_not_reset_a_finished_jobs_schedule(store):
    """Otherwise the cycle would re-run every source each hour regardless of its cadence."""
    store.enqueue(rows(("web_source", "yle", {"poll_minutes": 240})))
    finish(store)
    scheduled = store.jobs.find_one({"_id": "web_source:yle"})["next_run_at"]

    store._clock.advance(60)
    store.enqueue(rows(("web_source", "yle", {"poll_minutes": 240})))
    assert store.jobs.find_one({"_id": "web_source:yle"})["next_run_at"] == scheduled


def test_dispatch_claim_rearms_due_work_without_help(store):
    """The cycle itself must do it; a fix that needs an operator to run a script is not a fix."""
    manifest = rows(("web_source", "yle", {"poll_minutes": 5}))
    first = dispatch_claim(store, manifest, worker_id="laskin", max_jobs=5,
                           capabilities=LASKIN_CAPABILITIES)
    assert [j["_job_id"] for j in first] == ["web_source:yle"]
    store.complete(first[0]["_job_id"], "laskin")

    store._clock.advance(301)
    again = dispatch_claim(store, manifest, worker_id="laskin", max_jobs=5,
                           capabilities=LASKIN_CAPABILITIES)
    assert [j["_job_id"] for j in again] == ["web_source:yle"], (
        "a recurring source must come back on its own cadence, not once per study")


def test_inactive_manifest_rows_are_not_even_enqueued(store):
    manifest = [
        {"kind": "web_source", "name": "live", "active": True},
        {"kind": "scholarly_query", "name": "off", "active": False},
    ]
    dispatch_claim(store, manifest, worker_id="laskin", max_jobs=5, capabilities=LASKIN_CAPABILITIES)
    assert store.jobs.find_one({"_id": "scholarly_query:off"}) is None
