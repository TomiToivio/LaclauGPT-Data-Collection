"""Infrastructure failures must not drain the queue (#378).

On 2026-10-28 the Allas project quota was exhausted, and every ingest failed with
`QuotaExceeded` while writing the raw object. The queue treated each failure as evidence
about the *job*: within one hour, three attempts were burned off every job and work that
was perfectly collectable was marked permanently failed.

An outage is not a verdict on the work. These tests pin the two behaviours apart.
"""

from __future__ import annotations

import mongomock

from laclaugpt_data_collection.distributed_jobs import JobLeaseStore, dispatch_finish


def _store() -> JobLeaseStore:
    store = JobLeaseStore(mongomock.MongoClient()["ai26"]["jobs"])
    store.ensure_indexes()
    return store


def _claim_one(store: JobLeaseStore, job_id: str) -> dict:
    lease = store.claim("w", ["non_browser"], limit=1)[0]
    assert lease["_id"] == job_id
    return lease


def test_an_outage_does_not_consume_the_retry_budget():
    store = _store()
    store.enqueue([{"job_id": "web_source:a", "kind": "web_source", "name": "a"}])
    for _ in range(4):
        _claim_one(store, "web_source:a")
        dispatch_finish(
            store,
            {"_job_id": "web_source:a", "kind": "web_source", "name": "a"},
            {"status": "error", "reason": "object_store_or_database_unavailable",
             "infrastructure": True},
            worker_id="w",
        )
    doc = store.jobs.find_one({"_id": "web_source:a"})
    assert doc["status"] == "pending"
    assert doc["attempts"] == 0


def test_a_source_failure_still_exhausts_its_attempts():
    store = _store()
    store.enqueue([{"job_id": "web_source:b", "kind": "web_source", "name": "b", "max_attempts": 1}])
    _claim_one(store, "web_source:b")
    dispatch_finish(
        store,
        {"_job_id": "web_source:b", "kind": "web_source", "name": "b"},
        {"status": "error", "reason": "collection_or_ingest_failed"},
        worker_id="w",
    )
    assert store.jobs.find_one({"_id": "web_source:b"})["status"] == "failed"


def test_refund_is_bounded_and_never_negative():
    store = _store()
    store.enqueue([{"job_id": "web_source:c", "kind": "web_source", "name": "c"}])
    _claim_one(store, "web_source:c")
    # Release twice: the second refund must not push attempts below zero.
    for _ in range(2):
        store.release("web_source:c", "w", error="outage", refund_attempt=True)
    doc = store.jobs.find_one({"_id": "web_source:c"})
    assert doc["attempts"] == 0
    assert doc["status"] == "pending"
