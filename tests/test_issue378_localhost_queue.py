"""Issue #378, localhost slice: this host's share of the AI26 queue.

The two properties that matter on a browser-capable host:

1. it claims through the shared queue, so the same source is not collected twice by two machines;
2. it never claims a browser kind — X capture belongs to the Firefox extension, and a claimed
   browser job would sit on a lease until it expired instead of being served.

``mongomock`` is used so the claim filter is exercised for real (the filter is the boundary).
"""
from __future__ import annotations

import mongomock
import pytest

from laclaugpt_data_collection.ai26_localhost_collect import plan_jobs
from laclaugpt_data_collection.distributed_jobs import JobLeaseStore


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def store() -> JobLeaseStore:
    lease = JobLeaseStore(mongomock.MongoClient().db.jobs, clock=Clock())
    lease.ensure_indexes()
    return lease


MANIFEST = {
    "bluesky_account": [{"name": "Timnit Gebru", "handle": "timnit.bsky.social", "priority": "P1"},
                        {"name": "Other Person", "handle": "other.bsky.social", "priority": "P2"}],
    "scholarly_query": [{"name": "algorithmic governance", "query": "alg gov",
                         "services": ["arxiv"], "priority": "P1"}],
    "x_account": [{"handle": "@example", "priority": "P1"}],
}


def test_without_a_dispatcher_every_planned_row_runs() -> None:
    planned, claimed, total = plan_jobs(MANIFEST)
    assert claimed == []
    assert total == 3
    assert [row.get("name") or row.get("handle") or row.get("query") for _, row in planned] == [
        "Timnit Gebru", "Other Person", "algorithmic governance"]


def test_the_queue_grants_only_the_jobs_this_worker_may_run(store) -> None:
    planned, claimed, total = plan_jobs(MANIFEST, dispatch=store, worker_id="blazer", max_jobs=2)
    assert len(claimed) == 2
    assert len(planned) == 2
    assert total == 3
    kinds = {kind for kind, _ in planned}
    assert kinds == {"bluesky_account", "scholarly_query"}


def test_a_browser_job_queued_by_someone_else_is_never_claimed_here(store) -> None:
    """This runner does not enqueue browser rows, but if one is queued it must stay untouched."""
    store.enqueue([{"job_id": "x_account:@example", "kind": "x_account", "name": "@example"}])
    planned, claimed, total = plan_jobs(MANIFEST, dispatch=store, worker_id="blazer", max_jobs=10)
    assert {kind for kind, _ in planned} == {"bluesky_account", "scholarly_query"}
    pending = store.status()["by_kind"]
    assert pending.get("x_account") == 1, "the browser job must still be waiting for the capture path"
    assert len(claimed) == 3


def test_manifest_mode_does_not_touch_the_queue(store) -> None:
    plan_jobs(MANIFEST)
    assert store.status()["by_status"] == {}


def test_job_identity_is_stable_across_hosts(store) -> None:
    """Two hosts reading the same manifest address the same queue entries, not two sets."""
    first, _claimed, _total = plan_jobs(MANIFEST, dispatch=store, worker_id="blazer", max_jobs=10)
    second, _c2, _t2 = plan_jobs(MANIFEST, dispatch=store, worker_id="desktop", max_jobs=10)
    # Whatever the first worker holds, the second cannot also be granted the same job.
    assert len(first) + len(second) <= 3
    assert store.status()["by_status"].get("pending", 0) + len(first) + len(second) == 3
