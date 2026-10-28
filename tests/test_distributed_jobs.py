"""Capability routing and lease semantics for the AI26 distributed queue (#378).

These run against ``mongomock`` so the Mongo query semantics in ``claim()`` are exercised for real
(the filter is the security boundary, so testing it against a hand-written fake would test the fake).
"""
from __future__ import annotations

import mongomock
import pytest

from laclaugpt_data_collection.distributed_jobs import (
    BROWSER_REQUIRED_KINDS,
    DONE,
    FAILED,
    LASKIN_CAPABILITIES,
    LOCALHOST_CAPABILITIES,
    NON_BROWSER_KINDS,
    PENDING,
    RUNNING,
    JobLeaseStore,
    capability_filter,
    requires_browser,
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
    collection = mongomock.MongoClient().db.jobs
    s = JobLeaseStore(collection, clock=Clock())
    s.ensure_indexes()
    return s


def jobs(*specs):
    return [
        {"job_id": jid, "kind": kind, "name": jid, "priority": prio}
        for jid, kind, prio in specs
    ]


def test_capability_filter_excludes_every_browser_kind():
    flt = capability_filter(LASKIN_CAPABILITIES)
    # Allowlist, not exclusion: an unclassified kind must not be claimable by a
    # browser-less worker, which is what the old $nin silently permitted.
    assert flt == {"kind": {"$in": sorted(NON_BROWSER_KINDS)}}
    assert capability_filter(LOCALHOST_CAPABILITIES) == {}


def test_browser_kinds_are_classified_explicitly():
    for kind in BROWSER_REQUIRED_KINDS:
        assert requires_browser(kind) is True
    assert requires_browser("web_source") is False


def test_laskin_is_never_offered_a_browser_job(store):
    store.enqueue(jobs(("x1", "x_account", 1), ("x2", "instagram_account", 1)))
    assert store.claim("laskin", LASKIN_CAPABILITIES, limit=5) == []


def test_laskin_claims_non_browser_work(store):
    store.enqueue(jobs(("x1", "x_account", 1), ("w1", "web_source", 2)))
    claimed = store.claim("laskin", LASKIN_CAPABILITIES, limit=5)
    assert [c["_id"] for c in claimed] == ["w1"]


def test_localhost_claims_browser_work(store):
    store.enqueue(jobs(("x1", "x_account", 1)))
    claimed = store.claim("desktop", LOCALHOST_CAPABILITIES, limit=1)
    assert [c["_id"] for c in claimed] == ["x1"]


def test_two_workers_never_claim_the_same_job(store):
    store.enqueue(jobs(("a", "web_source", 1), ("b", "web_source", 1)))
    first = store.claim("laskin", LASKIN_CAPABILITIES, limit=2)
    second = store.claim("desktop", LOCALHOST_CAPABILITIES, limit=2)
    ids = [c["_id"] for c in first] + [c["_id"] for c in second]
    assert sorted(ids) == ["a", "b"]
    assert len(ids) == len(set(ids))


def test_expired_lease_becomes_reclaimable(store):
    store.enqueue(jobs(("a", "web_source", 1)))
    clock = store._clock
    assert store.claim("laskin", LASKIN_CAPABILITIES, limit=1, lease_seconds=60)
    assert store.claim("desktop", LOCALHOST_CAPABILITIES, limit=1) == []
    clock.advance(61)
    reclaimed = store.claim("desktop", LOCALHOST_CAPABILITIES, limit=1)
    assert [c["_id"] for c in reclaimed] == ["a"]
    assert reclaimed[0]["worker_id"] == "desktop"


def test_reaper_returns_expired_leases(store):
    store.enqueue(jobs(("a", "web_source", 1)))
    store.claim("laskin", LASKIN_CAPABILITIES, limit=1, lease_seconds=10)
    store._clock.advance(11)
    assert store.reap_expired() == 1
    assert store.jobs.find_one({"_id": "a"})["status"] == PENDING


def test_renew_extends_the_lease(store):
    store.enqueue(jobs(("a", "web_source", 1)))
    store.claim("laskin", LASKIN_CAPABILITIES, limit=1, lease_seconds=10)
    store._clock.advance(9)
    assert store.renew("a", "laskin", lease_seconds=60) is True
    store._clock.advance(30)
    store.reap_expired()
    assert store.jobs.find_one({"_id": "a"})["status"] == RUNNING


def test_completion_is_idempotent(store):
    store.enqueue(jobs(("a", "web_source", 1)))
    store.claim("laskin", LASKIN_CAPABILITIES, limit=1)
    assert store.complete("a", "laskin", outcome="ok") is True
    assert store.complete("a", "laskin", outcome="ok") is False
    assert store.jobs.find_one({"_id": "a"})["status"] == DONE


def test_another_worker_cannot_complete_someone_elses_job(store):
    store.enqueue(jobs(("a", "web_source", 1)))
    store.claim("laskin", LASKIN_CAPABILITIES, limit=1)
    assert store.complete("a", "desktop") is False
    assert store.jobs.find_one({"_id": "a"})["status"] == RUNNING


def test_attempts_are_bounded(store):
    store.enqueue([{"job_id": "a", "kind": "web_source", "max_attempts": 1}])
    claimed = store.claim("laskin", LASKIN_CAPABILITIES, limit=1)
    assert claimed[0]["attempts"] == 1
    store.release("a", "laskin", error="boom")
    doc = store.jobs.find_one({"_id": "a"})
    assert doc["status"] == FAILED
    assert doc["last_error"] == "boom"
    assert store.claim("laskin", LASKIN_CAPABILITIES, limit=1) == []


def test_release_returns_job_to_queue(store):
    store.enqueue([{"job_id": "a", "kind": "web_source", "max_attempts": 3}])
    store.claim("laskin", LASKIN_CAPABILITIES, limit=1)
    store.release("a", "laskin", error="network")
    assert store.jobs.find_one({"_id": "a"})["status"] == PENDING
    assert [c["_id"] for c in store.claim("desktop", LOCALHOST_CAPABILITIES, limit=1)] == ["a"]


def test_enqueue_is_idempotent(store):
    payload = jobs(("a", "web_source", 1), ("b", "x_account", 1))
    assert store.enqueue(payload) == 2
    assert store.enqueue(payload) == 0
    assert store.jobs.count_documents({}) == 2


def test_enqueue_requires_identity(store):
    with pytest.raises(ValueError):
        store.enqueue([{"kind": "web_source"}])
    with pytest.raises(ValueError):
        store.enqueue([{"job_id": "a"}])


def test_priority_ordering(store):
    store.enqueue(jobs(("p3", "web_source", 3), ("p1", "web_source", 1), ("p2", "web_source", 2)))
    claimed = store.claim("laskin", LASKIN_CAPABILITIES, limit=3)
    assert [c["_id"] for c in claimed] == ["p1", "p2", "p3"]


def test_status_reports_queue_and_workers(store):
    store.enqueue(jobs(("a", "web_source", 1), ("b", "x_account", 1), ("c", "web_source", 1)))
    store.claim("laskin", LASKIN_CAPABILITIES, limit=1)
    store.claim("desktop", LOCALHOST_CAPABILITIES, limit=1)
    status = store.status()
    assert status["by_status"][RUNNING] == 2
    assert status["by_status"][PENDING] == 1
    assert status["queue_depth"] == 3
    assert status["active_leases"] == 2
    assert status["expired_leases"] == 0
    assert set(status["workers"]) == {"laskin", "desktop"}
    # no payload contents leak into the operator view
    assert "payload" not in str(status)


def test_status_counts_expired_leases(store):
    store.enqueue(jobs(("a", "web_source", 1)))
    store.claim("laskin", LASKIN_CAPABILITIES, limit=1, lease_seconds=5)
    store._clock.advance(10)
    assert store.status()["expired_leases"] == 1
