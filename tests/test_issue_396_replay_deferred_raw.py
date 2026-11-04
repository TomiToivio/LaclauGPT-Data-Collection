"""#396: a deferred raw capture is a debt, and a debt needs a collector.

``distributed_capture`` keeps the record and marks ``raw_capture_pending``; nothing retried the
upload, so the marker could outlive the outage indefinitely. These tests pin the replay contract:
upload, clear the marker, and *do not* clear it when the store is still full.
"""
from __future__ import annotations

import mongomock

from laclaugpt_data_collection.raw_replay import pending_count, replay_pending


class Objects:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.put: list[tuple[str, bytes]] = []

    def put_bytes(self, key, body, *, content_type=None):
        if self.fail:
            raise RuntimeError("QuotaExceeded")
        self.put.append((key, body))
        return f"s3://bucket/{key}"


def record(*, payload=True, run_id="run-1") -> dict:
    doc = {
        "project_id": "ai26",
        "raw_capture": {"ref": None, "checksum": None,
                        "payload": {"text": "hello"} if payload else None},
        "provenance": [{"run_id": None,
                        "metadata": {"run_id": run_id, "raw_capture_pending": "quota_exhausted",
                                     "project_id": "ai26"}}],
    }
    return doc


def store_with(*docs):
    col = mongomock.MongoClient().db.ai26__records
    for doc in docs:
        col.insert_one(doc)
    return col


def test_a_deferred_capture_is_uploaded_and_the_marker_cleared():
    col = store_with(record())
    objects = Objects()
    report = replay_pending(col, objects, project_id="ai26")
    assert report["replayed"] == 1
    assert len(objects.put) == 1
    saved = col.find_one({})
    assert saved["raw_capture"]["ref"].startswith("s3://bucket/runs/run-1/raw/")
    assert saved["raw_capture"]["checksum"].startswith("sha256:")
    assert "raw_capture_pending" not in saved["provenance"][0]["metadata"]
    assert saved["provenance"][0]["metadata"]["project_id"] == "ai26"  # untouched
    assert pending_count(col) == 0


def test_a_store_that_is_still_full_keeps_the_debt_visible():
    col = store_with(record())
    report = replay_pending(col, Objects(fail=True), project_id="ai26",
                            classify_failure=lambda exc: "quota_exhausted")
    assert report["deferred"] == 1 and report["replayed"] == 0
    saved = col.find_one({})
    assert saved["provenance"][0]["metadata"]["raw_capture_pending"] == "quota_exhausted"
    assert pending_count(col) == 1


def test_a_record_without_a_payload_is_skipped_not_invented():
    col = store_with(record(payload=False))
    objects = Objects()
    report = replay_pending(col, objects, project_id="ai26")
    assert report["skipped_no_payload"] == 1
    assert objects.put == []


def test_dry_run_reports_without_touching_anything():
    col = store_with(record())
    objects = Objects()
    report = replay_pending(col, objects, project_id="ai26", dry_run=True)
    assert report["examined"] == 1 and report["replayed"] == 0
    assert objects.put == []
    assert pending_count(col) == 1


def test_the_pass_is_idempotent():
    col = store_with(record())
    replay_pending(col, Objects(), project_id="ai26")
    second = replay_pending(col, Objects(), project_id="ai26")
    assert second["examined"] == 0


def test_another_project_is_not_touched():
    col = store_with(record())
    col.update_one({}, {"$set": {"project_id": "brazil26"}})
    report = replay_pending(col, Objects(), project_id="ai26")
    assert report["examined"] == 0
