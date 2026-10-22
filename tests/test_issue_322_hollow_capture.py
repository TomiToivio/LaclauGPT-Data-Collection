"""Regression tests for #322: hollow AI26 records must fail closed.

All fixtures are synthetic; tests never touch production MongoDB or S3.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from laclaugpt_data_collection.distributed_capture import DistributedCaptureSink


@pytest.mark.parametrize(
    "source_url",
    [
        "https://x.com/example/status/123456789",
        "https://example.invalid/post/1",
    ],
)
def test_hollow_record_rejected_before_any_storage_or_publication(source_url: str) -> None:
    sink = object.__new__(DistributedCaptureSink)
    calls: list[str] = []
    sink.settings = SimpleNamespace(project_id="ai26", run_id="test")
    sink.objects = SimpleNamespace(put_bytes=lambda *a, **k: calls.append("s3"))
    sink.records = SimpleNamespace(upsert=lambda record: calls.append("mongo"))
    sink.redis = SimpleNamespace(publish_stream=lambda *a, **k: calls.append("redis"))

    with pytest.raises(ValueError, match="refusing hollow capture"):
        sink.ingest_with_status({"source_url": source_url})
    assert calls == []


@pytest.mark.parametrize(
    "evidence",
    [
        {"content": {"text": "synthetic post"}},
        {"raw_capture": {"payload": {"text": "synthetic raw content"}}},
        {"raw_capture": {"ref": "s3://synthetic-bucket/raw/example.json"}},
        {"content": {"media_references": [{"url": "https://example.invalid/photo.jpg"}]}},
    ],
)
def test_record_with_evidence_passes_hollow_guard(evidence: dict) -> None:
    sink = object.__new__(DistributedCaptureSink)
    record = {"source_url": "https://example.invalid/post/1", **evidence}
    sink.settings = SimpleNamespace(
        project_id="other", run_id="test", machine="test", execution="test",
        distributed_namespace=SimpleNamespace(mongo_collection=lambda _: "test_records"),
    )
    sink._raw_object = lambda record: ""
    sink.records = SimpleNamespace(upsert=lambda record: True)
    sink.redis = None
    sink.notification_errors = []
    stored, created = sink.ingest_with_status(record)
    assert created is True
    assert stored.source_url == record["source_url"]
