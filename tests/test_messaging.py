from __future__ import annotations

import json

import pytest

from laclaugpt_data_collection.messaging import (
    DirectPublisher,
    DurableRef,
    RedisStreamPublisher,
    TaskEnvelope,
    idempotency_key,
    publisher_from_environment,
)
from laclaugpt_data_collection.distributed import ProjectNamespace


class FakeRedis:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []
        self.dedupe: set[str] = set()
        self.heartbeats: dict[str, tuple[int, str]] = {}

    def eval(self, script: str, numkeys: int, stream: str, dedupe: str, payload: str, message_id: str):
        assert "XADD" in script
        assert numkeys == 2
        if dedupe in self.dedupe:
            return ["duplicate", ""]
        self.entries.append((stream, payload))
        self.dedupe.add(dedupe)
        return ["published", f"1-{len(self.entries)}"]

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.heartbeats[key] = (ttl, value)


def _envelope() -> TaskEnvelope:
    return TaskEnvelope(
        project_id="ai26",
        run_id="run-test",
        task_type="analysis.requested",
        source_url="https://example.invalid/post/1",
        idempotency_key=idempotency_key(
            project_id="ai26",
            operation="analysis.requested",
            identity="https://example.invalid/post/1",
            revision="v1",
        ),
        schema_revision="research-record-1.0",
        config_revision="synthetic-config-v1",
        refs=(DurableRef(kind="mongodb", uri="mongodb-ref://ai26/records/1"),),
        metadata={"collector": "synthetic"},
    )


def test_direct_mode_is_noop_without_redis_service() -> None:
    result = DirectPublisher().publish("analysis-requested", _envelope())
    assert result.backend == "direct"
    assert result.published is False
    assert result.duplicate is False


def test_factory_direct_mode_does_not_require_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LACLAUGPT_REDIS_URL", raising=False)
    publisher = publisher_from_environment(project_id="ai26", backend="direct")
    assert isinstance(publisher, DirectPublisher)


def test_redis_mode_requires_private_runtime_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LACLAUGPT_REDIS_URL", raising=False)
    with pytest.raises(RuntimeError, match="LACLAUGPT_REDIS_URL"):
        publisher_from_environment(project_id="ai26", backend="redis", client=FakeRedis())


def test_envelope_contains_references_not_large_payloads() -> None:
    envelope = _envelope()
    data = envelope.to_dict()
    assert data["project_id"] == "ai26"
    assert data["source_url"] == "https://example.invalid/post/1"
    assert data["refs"] == [
        {"kind": "mongodb", "uri": "mongodb-ref://ai26/records/1", "sha256": None}
    ]
    assert "payload" not in data
    assert "content" not in data


def test_envelope_rejects_non_scalar_metadata() -> None:
    with pytest.raises(TypeError, match="scalar JSON primitives"):
        TaskEnvelope(
            project_id="ai26",
            run_id="run-test",
            task_type="analysis.requested",
            source_url="https://example.invalid/post/1",
            idempotency_key="key",
            refs=(DurableRef(kind="file", uri="file:///tmp/record.json"),),
            metadata={"private_blob": {"not": "allowed"}},  # type: ignore[dict-item]
        )


def test_redis_publish_is_idempotent() -> None:
    fake = FakeRedis()
    publisher = RedisStreamPublisher(
        redis_url="redis://private.invalid/0",
        namespace=ProjectNamespace("ai26"),
        client=fake,
    )
    envelope = _envelope()

    first = publisher.publish("analysis-requested", envelope)
    second = publisher.publish("analysis-requested", envelope)

    assert first.published is True
    assert first.stream_entry_id == "1-1"
    assert second.published is False
    assert second.duplicate is True
    assert len(fake.entries) == 1
    stream, payload = fake.entries[0]
    assert stream == "laclaugpt:ai26:stream:analysis-requested"
    decoded = json.loads(payload)
    assert decoded["idempotency_key"] == envelope.idempotency_key
    assert decoded["refs"][0]["kind"] == "mongodb"


def test_redis_publisher_rejects_project_mismatch() -> None:
    publisher = RedisStreamPublisher(
        redis_url="redis://private.invalid/0",
        namespace=ProjectNamespace("ep24"),
        client=FakeRedis(),
    )
    with pytest.raises(ValueError, match="project_id"):
        publisher.publish("analysis-requested", _envelope())


def test_worker_heartbeat_is_small_and_expiring() -> None:
    fake = FakeRedis()
    publisher = RedisStreamPublisher(
        redis_url="redis://private.invalid/0",
        namespace=ProjectNamespace("ai26"),
        client=fake,
        heartbeat_ttl_seconds=60,
    )
    publisher.heartbeat(
        run_id="run-test",
        worker_id="server-collector-1",
        status="busy",
        current_task_id="task-1",
        metadata={"source": "rss"},
    )
    key = "laclaugpt:ai26:worker:collection:server-collector-1"
    ttl, raw = fake.heartbeats[key]
    assert ttl == 60
    payload = json.loads(raw)
    assert payload["worker_role"] == "collection"
    assert payload["status"] == "busy"
    assert payload["metadata"] == {"source": "rss"}


def test_idempotency_key_is_stable_and_does_not_embed_source_url() -> None:
    kwargs = {
        "project_id": "ai26",
        "operation": "collect.complete",
        "identity": "https://example.invalid/private-ish/url/1",
        "revision": "collector-v1",
    }
    first = idempotency_key(**kwargs)
    second = idempotency_key(**kwargs)
    assert first == second
    assert "example.invalid" not in first
