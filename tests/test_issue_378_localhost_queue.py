"""Localhost slice of #378: capability routing, queue dispatch and health (#378).

The Laskin worker was wired to the shared queue first (#380, #382). This host differs in one
way that matters: it *declares* the browser capability, but its collector cannot drive
Firefox (#258 keeps browser navigation user-controlled), so the CLI must still only claim
non-browser work while the queue backlog for X stays visible to the operator.

These tests pin that split: the capability is passed by the caller instead of being baked
into ``dispatch_claim``, a non-browser worker is never eligible for a browser job, and the
status board counts the backlog nobody may take.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from laclaugpt_data_collection.ai26_localhost_collect import (  # noqa: E402
    _manifest_jobs,
    _run_job,
    queue_health,
)
from laclaugpt_data_collection.distributed_jobs import (  # noqa: E402
    BROWSER_REQUIRED_KINDS,
    LOCALHOST_CAPABILITIES,
    PENDING,
    queue_snapshot,
    requires_browser,
)


class FakeDispatch:
    """Records what the caller asked for; no MongoDB."""

    def __init__(self) -> None:
        self.capabilities: set[str] = set()
        self.claimed: list[dict[str, Any]] = []

    def enqueue(self, rows, *, study_fingerprint=None):
        return len(rows)

    def reap_expired(self):
        return 0

    def claim(self, worker_id, capabilities, *, limit=1, lease_seconds=900):
        self.capabilities = set(capabilities)
        return self.claimed[:limit]


def test_manifest_jobs_cover_only_executable_kinds() -> None:
    manifest = {
        "bluesky_account": [{"handle": "a.bsky.social"}],
        "scholarly_query": [
            {"query": "ai governance", "services": ["arxiv"]},
            {"query": "not arxiv", "services": ["openalex"]},
        ],
    }
    jobs = _manifest_jobs(manifest)
    assert [(j["kind"], j["name"]) for j in jobs] == [
        ("bluesky_account", "a.bsky.social"),
        ("scholarly_query", "ai governance"),
    ]
    assert all(not requires_browser(j["kind"]) for j in jobs)


def test_dispatch_claim_uses_the_callers_capabilities() -> None:
    from laclaugpt_data_collection.distributed_jobs import dispatch_claim

    fake = FakeDispatch()
    dispatch_claim(fake, [{"kind": "web_source", "name": "s"}],
                   worker_id="localhost-a", max_jobs=3, capabilities={"non_browser"})
    assert fake.capabilities == {"non_browser"}
    # The default stays the restrictive Laskin role, so an old call site cannot widen itself.
    dispatch_claim(FakeDispatch(), [], worker_id="x", max_jobs=1)
    second = FakeDispatch()
    dispatch_claim(second, [], worker_id="x", max_jobs=1)
    assert "browser" not in second.capabilities


def test_a_non_browser_worker_is_never_eligible_for_browser_work() -> None:
    docs = [
        {"status": PENDING, "kind": "x_account"},
        {"status": PENDING, "kind": "web_source"},
        {"status": "done", "kind": "web_source"},
    ]
    snapshot = queue_snapshot(docs, {"non_browser"})
    assert snapshot["browser_backlog"] == 1
    assert snapshot["eligible_pending"] == 1
    assert snapshot["browser_capable"] is False

    capable = queue_snapshot(docs, LOCALHOST_CAPABILITIES)
    assert capable["browser_capable"] is True
    assert capable["eligible_pending"] == 2


def test_every_browser_kind_counts_as_backlog() -> None:
    docs = [{"status": PENDING, "kind": kind} for kind in sorted(BROWSER_REQUIRED_KINDS)]
    snapshot = queue_snapshot(docs, {"non_browser"})
    assert snapshot["browser_backlog"] == len(BROWSER_REQUIRED_KINDS)
    assert snapshot["eligible_pending"] == 0


def test_health_reports_the_backlog_without_mutating_jobs() -> None:
    class Collection:
        def find(self, *_args, **_kwargs):
            return [{"status": PENDING, "kind": "x_account"}]

    class Dispatch:
        jobs = Collection()

    health = queue_health(Dispatch(), capabilities={"non_browser"})
    assert health["worker_kind"] == "localhost"
    assert health["browser_backlog"] == 1
    assert health["browser_capture"].startswith("manual")


def test_an_unknown_job_kind_fails_loudly() -> None:
    with pytest.raises(ValueError, match="no executor"):
        _run_job(None, None, {"kind": "x_account", "name": "x", "row": {}},
                 project_id="ai26", collection_id="ai26", machine="desktop", run_id="")
