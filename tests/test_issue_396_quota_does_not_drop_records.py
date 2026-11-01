"""A full object store must not destroy a collected record (#396).

On 2026-10-28 19:05 an exhausted CSC Allas quota made every raw upload raise ``QuotaExceeded``. The
raw upload happened *before* the Mongo upsert, so each collected record was discarded — about 30 per
cycle, with nothing on disk to retry.

The contract this file pins:

* a quota (or transient transport) failure defers the raw object, and the record still reaches MongoDB;
* the deferred state is recorded on the record, so the gap is visible rather than silent;
* every other object-store failure still raises — a wrong bucket or expired credential is not a
  condition to work around;
* ``QuotaExceeded`` classifies as its own reason, not as ``unknown``.
"""
from __future__ import annotations

import pytest

from laclaugpt_data_collection.distributed_capture import (
    DEFERRABLE_RAW_REASONS,
    DistributedCaptureSink,
)
from laclaugpt_data_collection.storage.remote import ObjectStoreError, classify_object_store_failure


class _Raising:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def put_bytes(self, *args, **kwargs):  # noqa: ANN002, ANN003 - signature parity
        self.calls += 1
        raise self.exc


class _Records:
    def __init__(self) -> None:
        self.upserted = []

    def upsert(self, record):  # noqa: ANN001 - protocol parity
        self.upserted.append(record)
        return True


class _Objects:
    def put_bytes(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return "s3://bucket/key"


def _sink(objects) -> DistributedCaptureSink:  # noqa: ANN001
    sink = DistributedCaptureSink.__new__(DistributedCaptureSink)
    sink.settings = type(
        "S",
        (),
        {
            "project_id": "ai26",
            "run_id": "ai26-distributed-001",
            "machine": "laskin",
            "execution": "cron",
            "distributed_namespace": type("N", (), {"mongo_collection": lambda self, n: f"ai26__{n}"})(),
        },
    )()
    sink.records = _Records()
    sink.objects = objects
    sink.redis = None
    sink.notification_errors = []
    sink.pending_raw_uploads = 0
    return sink


def _payload(url: str = "https://example.org/a") -> dict:
    return {
        "source_url": url,
        "source": {"platform": "rss", "source_type": "rss"},
        "content": {"text": "Body text", "title": "Title"},
        "raw_capture": {"payload": {"html": "<p>Body</p>"}},
        "provenance": [{"module": "tests", "metadata": {"collection_id": "ai26"}}],
    }


def test_quota_exceeded_is_its_own_reason():
    exc = Exception("An error occurred (QuotaExceeded) when calling the PutObject operation")
    exc.response = {"Error": {"Code": "QuotaExceeded"}}  # type: ignore[attr-defined]
    assert classify_object_store_failure(exc) == "quota_exhausted"


def test_quota_failure_keeps_the_record_and_marks_it():
    sink = _sink(_Raising(ObjectStoreError("upload failed", reason="quota_exhausted")))
    record, created = sink.ingest_with_status(_payload())
    assert created is True
    assert sink.records.upserted == [record], "the record was dropped instead of stored"
    assert sink.pending_raw_uploads == 1
    assert record.provenance[-1].metadata.get("raw_capture_pending") == "quota_exhausted"
    assert not record.raw_capture.ref, "a missing object must not be recorded as a reference"


def test_transient_transport_is_also_deferred():
    sink = _sink(_Raising(ObjectStoreError("timed out", reason="transient_transport")))
    sink.ingest_with_status(_payload())
    assert sink.pending_raw_uploads == 1


@pytest.mark.parametrize("reason", ["credential_rejected", "bucket_or_prefix_wrong", "unknown"])
def test_other_storage_failures_still_raise(reason: str):
    sink = _sink(_Raising(ObjectStoreError("nope", reason=reason)))
    with pytest.raises(ObjectStoreError):
        sink.ingest_with_status(_payload())
    assert sink.records.upserted == []


def test_a_successful_upload_marks_nothing_pending():
    sink = _sink(_Objects())
    record, _ = sink.ingest_with_status(_payload())
    assert sink.pending_raw_uploads == 0
    assert "raw_capture_pending" not in record.provenance[-1].metadata
    assert record.raw_capture.ref == "s3://bucket/key"


def test_the_deferrable_set_is_small_on_purpose():
    assert DEFERRABLE_RAW_REASONS == frozenset({"quota_exhausted", "transient_transport"})
