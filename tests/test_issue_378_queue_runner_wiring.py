"""Queue-wiring tests for the Laskin runner (#378).

The lease queue already had a proven capability rule; what was missing is that the
runner never consulted it, so every host ran its own copy of the manifest. These tests
cover the wiring itself: what gets claimed, what is completed versus released, and that
Laskin still cannot be handed browser work through this path.
"""

from __future__ import annotations

import mongomock
import pytest

from laclaugpt_data_collection import ai26_laskin_runner as R
from laclaugpt_data_collection.distributed_jobs import JobLeaseStore


def _store() -> JobLeaseStore:
    client = mongomock.MongoClient()
    store = JobLeaseStore(client["ai26"]["ai26_jobs_test"])
    store.ensure_indexes()
    return store


def _manifest_rows():
    return [
        {"job_id": "web_source:alpha", "kind": "feeds", "name": "alpha", "priority": 1},
        {"job_id": "youtube_source:beta", "kind": "youtube_channel", "name": "beta", "priority": 2},
    ]


@pytest.fixture()
def patched(monkeypatch, tmp_path):
    manifest = tmp_path / "sources.toml"
    manifest.write_text(
        '[[web_source]]\nname = "alpha"\nurl = "https://example.test/a"\n'
        '[[youtube_source]]\nname = "beta"\nurl = "https://example.test/b"\n',
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_run(settings, *, claimed_jobs=None, **kwargs):
        calls.append([j["job_id"] for j in (claimed_jobs or [])])
        return {
            "status": "ok",
            "errors": [],
            "source_outcomes": [
                {"kind": j["kind"], "name": j["name"], "status": "ok", "reason": ""}
                for j in (claimed_jobs or [])
            ],
        }

    monkeypatch.setattr(R, "run_phase1_laskin", fake_run)
    return manifest, calls


def test_queue_rows_use_stable_ids_and_normalise_priority():
    rows = R.queue_rows_from_manifest(
        [{"kind": "web_source", "name": "a", "priority": "P1"},
         {"kind": "web_source", "name": "b", "priority": 3}]
    )
    assert [r["job_id"] for r in rows] == ["web_source:a", "web_source:b"]
    assert [r["priority"] for r in rows] == [1, 3]


def test_claim_runs_and_completes_claimed_jobs(patched):
    manifest, calls = patched
    store = _store()
    result = R.run_queued_laskin_cycle(
        object(), store=store, study_config=manifest, source_manifest=manifest, max_jobs=2
    )
    assert result["queue"]["claimed"] == 2
    assert result["queue"]["completed"] == 2
    assert result["queue"]["released"] == 0
    assert calls and sorted(calls[0]) == ["web_source:alpha", "youtube_source:beta"]
    assert store.jobs.count_documents({"status": "done"}) == 2


def test_reenqueue_is_idempotent_across_cycles(patched):
    manifest, _ = patched
    store = _store()
    R.run_queued_laskin_cycle(object(), store=store, study_config=manifest, source_manifest=manifest)
    second = R.run_queued_laskin_cycle(
        object(), store=store, study_config=manifest, source_manifest=manifest
    )
    # Same manifest: nothing new is inserted, and the finished jobs are not rerun.
    assert second["queue"]["enqueued"] == 0
    assert store.jobs.count_documents({}) == 2


def test_deferred_job_is_released_not_completed(patched, monkeypatch):
    manifest, _ = patched

    def fake_run(settings, *, claimed_jobs=None, **kwargs):
        return {"status": "ok", "errors": [], "source_outcomes": [
            {"kind": j["kind"], "name": j["name"],
             "status": "deferred" if j["job_id"] == "web_source:alpha" else "ok",
             "reason": "tick_record_limit"} for j in (claimed_jobs or [])]}

    monkeypatch.setattr(R, "run_phase1_laskin", fake_run)
    store = _store()
    result = R.run_queued_laskin_cycle(
        object(), store=store, study_config=manifest, source_manifest=manifest, max_jobs=2
    )
    assert result["queue"]["completed"] == 1
    assert result["queue"]["released"] == 1
    released = store.jobs.find_one({"_id": "web_source:alpha"})
    assert released["status"] == "pending" and released["last_error"] == "tick_record_limit"


def test_lease_whose_job_left_the_manifest_is_released(patched):
    manifest, _ = patched
    store = _store()
    client = mongomock.MongoClient()
    orphan_store = JobLeaseStore(client["x"]["c"])
    orphan_store.enqueue([{"job_id": "web_source:gone", "kind": "web_source", "name": "gone"}])
    orphan_store.claim("w", ["non_browser"], limit=1)
    # Simulate that claim happening in the same collection our cycle uses.
    store.enqueue([{"job_id": "web_source:gone", "kind": "web_source", "name": "gone"}])
    store.claim("w", ["non_browser"], limit=1)

    # The cycle's manifest does not contain feeds:gone, so the lease is orphaned.
    rows = R.queue_rows_from_manifest(R.load_non_browser_jobs(manifest))
    jobs, orphaned = R.claimed_jobs_for_run([{"_id": "web_source:gone"}, {"_id": "web_source:alpha"}], rows)
    assert orphaned == ["web_source:gone"]
    assert [j["job_id"] for j in jobs] == ["web_source:alpha"]


def test_laskin_cannot_claim_a_browser_job_through_the_cycle(tmp_path, monkeypatch):
    """The capability rule is in the claim query, so this path cannot bypass it."""
    manifest = tmp_path / "sources.toml"
    manifest.write_text('[[web_source]]\nname = "alpha"\nurl = "https://example.test/a"\n', encoding="utf-8")
    store = _store()
    # x_search is deliberately NOT in either classified set: the point of the probe is
    # that an unclassified kind must not reach a browser-less worker.
    store.enqueue([{"job_id": "x_search:q", "kind": "x_search", "name": "q", "priority": 1}])
    monkeypatch.setattr(R, "run_phase1_laskin",
                        lambda *a, **k: {"status": "ok", "errors": [], "source_outcomes": []})
    result = R.run_queued_laskin_cycle(
        object(), store=store, study_config=manifest, source_manifest=manifest, max_jobs=3
    )
    claimed_ids = [d["_id"] for d in store.jobs.find({"status": "running"})]
    assert "x_search:q" not in claimed_ids
    assert result["queue"]["claimed"] == 1  # only the non-browser feed job


def test_no_mongo_uri_means_no_store():
    class S:
        mongodb_uri = ""

    assert R.queue_store(S()) is None


def test_unclassified_kind_is_denied_not_allowed():
    """The capability filter is an allowlist.

    It used to exclude the known browser kinds, which meant anything unclassified —
    including a future browser kind — was claimable on Laskin. Verified against the live
    queue on 2026-10-28: x_account was refused, x_search was claimed.
    """
    from laclaugpt_data_collection.distributed_jobs import capability_filter

    clause = capability_filter(R.LASKIN_CAPABILITIES)
    assert clause["kind"]["$in"], "expected an allowlist"
    store = _store()
    store.enqueue([
        {"job_id": "x_account:known-browser", "kind": "x_account", "name": "b"},
        {"job_id": "x_search:unclassified", "kind": "x_search", "name": "u"},
        {"job_id": "web_source:fine", "kind": "web_source", "name": "f"},
    ])
    claimed = {d["_id"] for d in store.claim("laskin-cron", R.LASKIN_CAPABILITIES, limit=10)}
    assert claimed == {"web_source:fine"}


def test_runner_uses_the_queue_modules_capability_set():
    """One canonical set: a second spelling silently asks for the wrong permission."""
    from laclaugpt_data_collection.distributed_jobs import LASKIN_CAPABILITIES as CANONICAL

    assert R.LASKIN_CAPABILITIES == CANONICAL
