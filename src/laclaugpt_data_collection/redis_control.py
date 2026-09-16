"""Optional Redis control-plane primitives for distributed Collection.

Redis coordinates project configuration, small operational messages and leases.
It is deliberately not a research datastore: canonical records and large payloads
must be persisted elsewhere before Redis messages/tasks are acknowledged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol

from .distributed import ProjectNamespace
from .effective_config import EffectiveCollectionConfig

_SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "cookie",
    "credential",
    "access_key",
    "api_key",
)


class RedisLike(Protocol):
    """Small subset used here so tests can use a fake client."""

    def get(self, name: str) -> Any: ...

    def set(self, name: str, value: Any, **kwargs: Any) -> Any: ...

    def xadd(self, name: str, fields: Mapping[str, Any], **kwargs: Any) -> Any: ...

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class ConfigRevision:
    project_id: str
    revision: str
    digest: str
    actor: str
    source: str
    created_at: str
    config: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "project_id": self.project_id,
            "module": "collection",
            "revision": self.revision,
            "digest": self.digest,
            "actor": self.actor,
            "source": self.source,
            "created_at": self.created_at,
            "config": self.config,
        }


class RedisProjectConfig:
    """Versioned project configuration stored under the shared LaclauGPT namespace."""

    def __init__(
        self,
        client: RedisLike,
        namespace: ProjectNamespace,
        *,
        snapshot_root: Path | None = None,
    ) -> None:
        self.client = client
        self.namespace = namespace
        self.snapshot_root = snapshot_root

    def publish(
        self,
        effective: EffectiveCollectionConfig,
        *,
        actor: str,
        source: str,
    ) -> ConfigRevision:
        """Publish a validated effective config and retain a durable local snapshot."""
        _reject_secrets(effective.data)
        revision = effective.digest.removeprefix("sha256:")[:16]
        item = ConfigRevision(
            project_id=self.namespace.project_id,
            revision=revision,
            digest=effective.digest,
            actor=actor,
            source=source,
            created_at=datetime.now(UTC).isoformat(),
            config=dict(effective.data),
        )
        payload = json.dumps(item.as_dict(), sort_keys=True, separators=(",", ":"), default=str)
        revision_key = self.namespace.settings_key("collection", revision)
        current_key = self.namespace.settings_key("collection", "current")
        self.client.set(revision_key, payload)
        self.client.set(current_key, revision)
        self._write_snapshot(item)
        return item

    def load(self, revision: str = "current") -> ConfigRevision:
        """Load current or explicit revision; current is an indirection key."""
        if revision == "current":
            value = self.client.get(self.namespace.settings_key("collection", "current"))
            if value is None:
                raise KeyError(f"no distributed collection config for {self.namespace.project_id}")
            revision = _decode(value)
        raw = self.client.get(self.namespace.settings_key("collection", revision))
        if raw is None:
            raise KeyError(f"unknown collection config revision: {revision}")
        data = json.loads(_decode(raw))
        return ConfigRevision(
            project_id=str(data["project_id"]),
            revision=str(data["revision"]),
            digest=str(data["digest"]),
            actor=str(data.get("actor") or "unknown"),
            source=str(data.get("source") or "unknown"),
            created_at=str(data["created_at"]),
            config=dict(data["config"]),
        )

    def export(self, path: Path, revision: str = "current") -> ConfigRevision:
        """Export a Redis revision as a JSON snapshot for reproducibility/offline use."""
        item = self.load(revision)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(item.as_dict(), indent=2, sort_keys=True, default=str) + "\n")
        return item

    def _write_snapshot(self, item: ConfigRevision) -> None:
        if self.snapshot_root is None:
            return
        path = self.snapshot_root / self.namespace.project_id / f"{item.revision}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(item.as_dict(), indent=2, sort_keys=True, default=str) + "\n")


class RedisEventBus:
    """Reference-only operational events using Redis Streams.

    This class exists now so modules can share an envelope, but AI26 Collection
    does not enable it by default yet.
    """

    def __init__(self, client: RedisLike, namespace: ProjectNamespace) -> None:
        self.client = client
        self.namespace = namespace

    def publish(
        self,
        event_type: str,
        *,
        sender: str,
        reference_id: str = "",
        run_id: str = "",
        correlation_id: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        envelope = {
            "schema_version": "1",
            "project_id": self.namespace.project_id,
            "module": "collection",
            "event_type": event_type,
            "sender": sender,
            "reference_id": reference_id,
            "run_id": run_id,
            "correlation_id": correlation_id,
            "created_at": datetime.now(UTC).isoformat(),
            "metadata_json": json.dumps(dict(metadata or {}), sort_keys=True, default=str),
        }
        result = self.client.xadd(self.namespace.stream_key("events"), envelope)
        return _decode(result)


class RedisLeaseCoordinator:
    """Small atomic lease primitive for future distributed task coordination.

    It intentionally does not activate a queue on its own. Callers must opt into
    the Redis task backend. A lease prevents two workers claiming the same
    idempotency key while durable task/result state remains outside Redis.
    """

    _RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""
    _RENEW = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""

    def __init__(self, client: RedisLike, namespace: ProjectNamespace) -> None:
        self.client = client
        self.namespace = namespace

    def claim(self, task_id: str, worker_id: str, *, ttl_seconds: int = 300) -> bool:
        key = self.namespace.redis_key("lease", "collection", task_id)
        return bool(self.client.set(key, worker_id, nx=True, ex=ttl_seconds))

    def renew(self, task_id: str, worker_id: str, *, ttl_seconds: int = 300) -> bool:
        key = self.namespace.redis_key("lease", "collection", task_id)
        return bool(self.client.eval(self._RENEW, 1, key, worker_id, ttl_seconds * 1000))

    def release(self, task_id: str, worker_id: str) -> bool:
        key = self.namespace.redis_key("lease", "collection", task_id)
        return bool(self.client.eval(self._RELEASE, 1, key, worker_id))


def redis_client(redis_url: str) -> RedisLike:
    """Create a decoded Redis client only when the optional backend is requested."""
    if not redis_url:
        raise ValueError("Redis backend requires LACLAUGPT_REDIS_URL")
    try:
        import redis
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("install laclaugpt-data-collection[distributed] for Redis support") from exc
    return redis.Redis.from_url(redis_url, decode_responses=True)


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _reject_secrets(value: Any, *, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            lowered = name.casefold()
            if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                dotted = ".".join((*path, name))
                raise ValueError(f"refusing to publish secret-like config key to Redis: {dotted}")
            _reject_secrets(item, path=(*path, name))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_secrets(item, path=(*path, str(index)))
