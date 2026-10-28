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
    PENDING,
    RUNNING,
    JobLeaseStore,
    capability_filter,
    dispatch_claim,
    dispatch_finish,
    job_identity,
    priority_rank,
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
    assert flt == {"kind": {"$nin": sorted(BROWSER_REQUIRED_KINDS)}}
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

def test_job_identity_is_stable_across_hosts():
    row = {"kind": "web_source", "name": "openai-news", "priority": "P1"}
    assert job_identity(row) == "web_source:openai-news"
    assert job_identity(dict(row)) == job_identity(row)


def test_job_identity_requires_kind_and_name():
    with pytest.raises(ValueError):
        job_identity({"kind": "web_source"})
    with pytest.raises(ValueError):
        job_identity({"name": "x"})


def test_dispatch_claim_returns_only_work_laskin_may_do(store):
    rows = [
        {"kind": "x_account", "name": "lula"},
        {"kind": "instagram_account", "name": "gov"},
        {"kind": "web_source", "name": "openai-news"},
    ]
    claimed = dispatch_claim(store, rows, worker_id="laskin", max_jobs=5)
    assert [c["name"] for c in claimed] == ["openai-news"]
    assert claimed[0]["_job_id"] == "web_source:openai-news"
    assert claimed[0]["kind"] == "web_source"


def test_dispatch_claim_is_empty_once_leased(store):
    rows = [{"kind": "web_source", "name": "openai-news"}]
    assert dispatch_claim(store, rows, worker_id="laskin", max_jobs=5)
    assert dispatch_claim(store, rows, worker_id="laskin", max_jobs=5) == []


def test_dispatch_finish_completes_success(store):
    rows = [{"kind": "web_source", "name": "s"}]
    claim = dispatch_claim(store, rows, worker_id="laskin", max_jobs=1)
    dispatch_finish(store, claim[0], {"status": "ok"}, worker_id="laskin")
    assert store.jobs.find_one({"_id": "web_source:s"})["status"] == DONE


def test_dispatch_finish_requeues_failure(store):
    rows = [{"kind": "web_source", "name": "s"}]
    claim = dispatch_claim(store, rows, worker_id="laskin", max_jobs=1)
    dispatch_finish(store, claim[0], {"status": "error", "reason": "boom"}, worker_id="laskin")
    doc = store.jobs.find_one({"_id": "web_source:s"})
    assert doc["status"] == PENDING
    assert doc["last_error"] == "boom"


def test_dispatch_finish_requeues_deferred_tick(store):
    rows = [{"kind": "web_source", "name": "s"}]
    claim = dispatch_claim(store, rows, worker_id="laskin", max_jobs=1)
    dispatch_finish(store, claim[0], {"status": "deferred"}, worker_id="laskin")
    assert store.jobs.find_one({"_id": "web_source:s"})["status"] == PENDING


def test_dispatch_finish_ignores_unleased_rows(store):
    dispatch_finish(store, {"kind": "web_source", "name": "s"}, {"status": "ok"}, worker_id="laskin")
    assert store.jobs.count_documents({}) == 0

def test_priority_accepts_manifest_notation(store):
    assert priority_rank("P1") == 1
    assert priority_rank("p3") == 3
    assert priority_rank(2) == 2
    assert priority_rank("2") == 2
    assert priority_rank(None) == 2
    store.enqueue([{"job_id": "a", "kind": "web_source", "priority": "P1"},
                   {"job_id": "b", "kind": "web_source", "priority": "P3"}])
    assert [c["_id"] for c in store.claim("laskin", LASKIN_CAPABILITIES, limit=2)] == ["a", "b"]


# --------------------------------------------------------------------------- #
# #378 localhost slice: a host may hold the browser capability and still not be
# able to execute a browser job. The queue must answer both questions.
# --------------------------------------------------------------------------- #

def test_claim_restricted_to_executable_kinds_never_returns_a_browser_job(store):
    from laclaugpt_data_collection.distributed_jobs import NON_BROWSER_KINDS

    store.enqueue(jobs(("x1", "x_account", 1), ("w1", "web_source", 1)))
    claimed = store.claim("localhost", LOCALHOST_CAPABILITIES, limit=5,
                          kinds=NON_BROWSER_KINDS)
    assert [job["kind"] for job in claimed] == ["web_source"]


def test_claim_with_an_empty_kind_set_claims_nothing(store):
    store.enqueue(jobs(("w1", "web_source", 1)))
    assert store.claim("localhost", LOCALHOST_CAPABILITIES, limit=5, kinds=[]) == []
    # ... and the job is untouched, not consumed by an empty claim
    assert store.status()["by_status"] == {PENDING: 1}


def test_dispatch_claim_is_laskin_safe_by_default(store):
    """The default must stay the behaviour the Laskin cron relies on."""
    rows = [{"kind": "x_account", "name": "x1"}, {"kind": "web_source", "name": "w1"}]
    claimed = dispatch_claim(store, rows, worker_id="laskin", max_jobs=5)
    assert [job["kind"] for job in claimed] == ["web_source"]


def test_dispatch_claim_on_a_browser_host_still_only_takes_runnable_work(store):
    """A browser-capable host claims its capability, but the runner cannot execute browser kinds."""
    rows = [{"kind": "x_account", "name": "x1"}, {"kind": "web_source", "name": "w1"}]
    claimed = dispatch_claim(store, rows, worker_id="blazer", max_jobs=5,
                             capabilities=LOCALHOST_CAPABILITIES)
    assert [job["kind"] for job in claimed] == ["web_source"]
    # the browser job is still pending for the capture path, not parked on a lease
    pending = store.status()["by_kind"]
    assert pending.get("x_account") == 1


def test_worker_id_names_the_host_not_laskin(monkeypatch):
    from laclaugpt_data_collection.ai26_laskin_runner import default_worker_id

    monkeypatch.delenv("LACLAUGPT_WORKER_ID", raising=False)
    monkeypatch.setattr("socket.gethostname", lambda: "BLAZER.local")
    assert default_worker_id() == "blazer-cron"
    monkeypatch.setenv("LACLAUGPT_WORKER_ID", "explicit-worker")
    assert default_worker_id() == "explicit-worker"
