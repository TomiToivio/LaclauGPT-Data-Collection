from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pytest

from laclaugpt_data_collection.distributed import ProjectNamespace
from laclaugpt_data_collection.effective_config import resolve_collection_config
from laclaugpt_data_collection.redis_control import (
    RedisEventBus,
    RedisLeaseCoordinator,
    RedisProjectConfig,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.streams: dict[str, list[dict[str, Any]]] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: Any, **kwargs: Any) -> bool:
        if kwargs.get("nx") and name in self.values:
            return False
        self.values[name] = str(value)
        return True

    def xadd(self, name: str, fields: Mapping[str, Any], **kwargs: Any) -> str:
        entries = self.streams.setdefault(name, [])
        entries.append(dict(fields))
        return f"1-{len(entries)}"

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> int:
        key = str(keys_and_args[0])
        owner = str(keys_and_args[1])
        if self.values.get(key) != owner:
            return 0
        if "del" in script:
            del self.values[key]
            return 1
        if "pexpire" in script:
            return 1
        raise AssertionError("unexpected fake Redis script")


def _effective() -> Any:
    return resolve_collection_config(
        project={
            "study": "ai26",
            "platforms": {"rss": {"enabled": True}},
            "distributed": {
                "config_backend": "redis",
                "messaging_backend": "none",
                "task_queue_backend": "direct",
            },
        }
    )


def test_versioned_config_publish_load_and_snapshot(tmp_path: Path) -> None:
    redis = FakeRedis()
    namespace = ProjectNamespace("ai26")
    store = RedisProjectConfig(redis, namespace, snapshot_root=tmp_path)

    published = store.publish(_effective(), actor="researcher", source="test")
    loaded = store.load()

    assert loaded.revision == published.revision
    assert loaded.digest == published.digest
    assert loaded.config["study"] == "ai26"
    assert loaded.config["distributed"]["messaging_backend"] == "none"
    assert (tmp_path / "ai26" / f"{published.revision}.json").is_file()


def test_config_publish_rejects_secret_like_keys() -> None:
    redis = FakeRedis()
    store = RedisProjectConfig(redis, ProjectNamespace("ai26"))
    effective = resolve_collection_config(
        project={"study": "ai26", "service": {"api_token": "do-not-publish"}}
    )

    with pytest.raises(ValueError, match="secret-like config key"):
        store.publish(effective, actor="researcher", source="test")


def test_event_bus_uses_reference_only_shared_stream() -> None:
    redis = FakeRedis()
    namespace = ProjectNamespace("ai26")
    bus = RedisEventBus(redis, namespace)

    event_id = bus.publish(
        "collection.record.stored",
        sender="collector:rss",
        reference_id="https://example.test/item/1",
        run_id="run-1",
    )

    assert event_id == "1-1"
    entry = redis.streams[namespace.stream_key("events")][0]
    assert entry["project_id"] == "ai26"
    assert entry["reference_id"] == "https://example.test/item/1"


def test_lease_prevents_duplicate_worker_claim() -> None:
    redis = FakeRedis()
    leases = RedisLeaseCoordinator(redis, ProjectNamespace("ai26"))

    assert leases.claim("source-123:rss", "worker-a", ttl_seconds=30)
    assert not leases.claim("source-123:rss", "worker-b", ttl_seconds=30)
    assert not leases.release("source-123:rss", "worker-b")
    assert leases.renew("source-123:rss", "worker-a", ttl_seconds=30)
    assert leases.release("source-123:rss", "worker-a")
    assert leases.claim("source-123:rss", "worker-b", ttl_seconds=30)
