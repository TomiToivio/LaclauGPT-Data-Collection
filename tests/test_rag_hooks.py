from __future__ import annotations

import json

import pytest

from laclaugpt_data_collection.models import (
    CanonicalRecord,
    CollectionProvenance,
    ContentSection,
    RawCaptureSection,
    SourceSection,
)
from laclaugpt_data_collection.rag import (
    ANALYSIS_ONLY_RELATIONS,
    graph_ready_payload,
    idempotency_key,
    index_after_save,
    validate_collection_relations,
)


def _record() -> CanonicalRecord:
    return CanonicalRecord(
        source_url="https://Example.org/post/1?utm_source=test",
        source_native_ids={"post_id": "1"},
        raw_capture=RawCaptureSection(
            ref="s3://private-bucket/raw/post-1.json",
            checksum="sha256:abc",
            metadata={"preservation": "durable-reference"},
        ),
        source=SourceSection(
            platform="mastodon",
            source_type="post",
            author="research-account",
            collected_at="2026-09-16T09:00:00+00:00",
            collector="mastodon-collector",
            collection_method="api",
            language="en",
            raw_ref="s3://private-bucket/raw/post-1.json",
            raw_metadata={"instance": "example.org"},
        ),
        content=ContentSection(text="A source statement.", language="en"),
        provenance=[
            CollectionProvenance(
                collector="mastodon-collector",
                collector_version="1.2.3",
                capture_id="capture-1",
            )
        ],
    )


class RecordingIndexer:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, str]] = []

    def index(self, payload: dict, *, idempotency_key: str) -> None:
        self.calls.append((payload, idempotency_key))


class FailingIndexer:
    def index(self, payload: dict, *, idempotency_key: str) -> None:
        raise ConnectionError("neo4j unavailable")


def test_rag_disabled_is_noop() -> None:
    indexer = RecordingIndexer()
    result = index_after_save(_record(), enabled=False, indexer=indexer, dataset="AI26")
    assert result.status == "disabled"
    assert indexer.calls == []


def test_unavailable_indexer_never_raises_and_is_replayable(tmp_path) -> None:
    failure_log = tmp_path / "rag-failures.jsonl"
    result = index_after_save(
        _record(),
        enabled=True,
        indexer=FailingIndexer(),
        dataset="AI26",
        failure_log=failure_log,
    )
    assert result.status == "failed"
    event = json.loads(failure_log.read_text(encoding="utf-8").strip())
    assert event["record_id"] == "https://example.org/post/1"
    assert event["idempotency_key"] == result.idempotency_key


def test_idempotency_key_is_stable_for_retry() -> None:
    record = _record()
    assert idempotency_key(record, dataset="AI26") == idempotency_key(record, dataset="AI26")


def test_graph_ready_payload_preserves_identity_and_provenance() -> None:
    payload = graph_ready_payload(_record(), dataset="AI26")
    assert payload["record_id"] == "https://example.org/post/1"
    assert payload["source_url"] == "https://example.org/post/1"
    assert payload["dataset"] == "AI26"
    assert payload["platform"] == "mastodon"
    assert payload["language"] == "en"
    assert payload["raw_ref"] == "s3://private-bucket/raw/post-1.json"
    assert payload["collector_version"] == "1.2.3"
    assert payload["provenance"][0]["capture_id"] == "capture-1"


def test_collection_emits_only_factual_relation_types() -> None:
    payload = graph_ready_payload(_record(), dataset="AI26")
    relation_types = {item["type"] for item in payload["factual_relations"]}
    assert relation_types == {"ON_PLATFORM", "IN_DATASET", "HAS_LANGUAGE"}
    assert not relation_types & ANALYSIS_ONLY_RELATIONS
    validate_collection_relations(payload)


def test_analysis_only_relation_guard_rejects_theoretical_inference() -> None:
    with pytest.raises(ValueError, match="analysis-only relations"):
        validate_collection_relations(
            {"factual_relations": [{"type": "ARTICULATED_WITH", "target": "AGI"}]}
        )


def test_enabled_indexing_receives_same_key_on_repeated_retry() -> None:
    record = _record()
    indexer = RecordingIndexer()
    first = index_after_save(record, enabled=True, indexer=indexer, dataset="AI26")
    second = index_after_save(record, enabled=True, indexer=indexer, dataset="AI26")
    assert first.status == second.status == "indexed"
    assert first.idempotency_key == second.idempotency_key
    assert [call[1] for call in indexer.calls] == [first.idempotency_key, first.idempotency_key]
