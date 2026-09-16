"""Optional messaging/task adapter for collection-side handoff.

Direct mode has no Redis dependency. Redis mode publishes small, pointer-rich
messages to project-scoped Redis Streams only after callers have committed the
durable collection state.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Mapping, Protocol

from .distributed import ProjectNamespace

Primitive = str | int | float | bool | None
DurableKind = Literal["mongodb", "s3", "https", "file", "sqlite", "jsonl"]


@dataclass(frozen=True, slots=True)
class DurableRef:
    kind: DurableKind
    uri: str
    sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.uri:
            raise ValueError("durable reference uri must not be empty")
        if self.sha256 is not None and (
            len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256)
        ):
            raise ValueError("sha256 must be a lowercase 64-character hex digest")


@dataclass(frozen=True, slots=True)
class TaskEnvelope:
    project_id: str
    run_id: str
    task_type: str
    idempotency_key: str
    refs: tuple[DurableRef, ...]
    source_url: str | None = None
    record_id: str | None = None
    arena: str | None = None
    schema_revision: str | None = None
    config_revision: str | None = None
    codebook_revision: str | None = None
    producer: str | None = "collection"
    metadata: Mapping[str, Primitive] = field(default_factory=dict)
    attempt: int = 1
    message_id: str = field(default_factory=lambda: f"msg-{uuid.uuid4()}")
    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4()}")
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    not_before: str | None = None
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        ProjectNamespace(self.project_id)
        if not self.run_id or not self.task_type or not self.idempotency_key:
            raise ValueError("run_id, task_type and idempotency_key are required")
        if self.source_url is None and self.record_id is None:
            raise ValueError("source_url or record_id is required")
        if self.attempt < 1:
            raise ValueError("attempt must be >= 1")
        if not self.refs:
            raise ValueError("at least one durable reference is required")
        if any(not isinstance(value, (str, int, float, bool, type(None))) for value in self.metadata.values()):
            raise TypeError("metadata values must be scalar JSON primitives")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["refs"] = [asdict(ref) for ref in self.refs]
        data["metadata"] = dict(self.metadata)
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True, slots=True)
class PublishResult:
    backend: Literal["direct", "redis"]
    published: bool
    duplicate: bool = False
    message_id: str | None = None
    stream_entry_id: str | None = None


class Publisher(Protocol):
    def publish(self, stream: str, envelope: TaskEnvelope) -> PublishResult: ...

    def heartbeat(
        self,
        *,
        run_id: str,
        worker_id: str,
        status: str,
        current_task_id: str | None = None,
        metadata: Mapping[str, Primitive] | None = None,
    ) -> None: ...


def idempotency_key(
    *, project_id: str, operation: str, identity: str, revision: str
) -> str:
    """Build a stable operation key without leaking a full source URL into Redis keys."""
    ProjectNamespace(project_id)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"{project_id}:{operation}:{digest}:{revision}"


class DirectPublisher:
    """No-op publisher for the default single-process/direct execution mode."""

    def publish(self, stream: str, envelope: TaskEnvelope) -> PublishResult:
        del stream
        return PublishResult(backend="direct", published=False, message_id=envelope.message_id)

    def heartbeat(
        self,
        *,
        run_id: str,
        worker_id: str,
        status: str,
        current_task_id: str | None = None,
        metadata: Mapping[str, Primitive] | None = None,
    ) -> None:
        del run_id, worker_id, status, current_task_id, metadata


# Atomically suppress duplicates and append the envelope. Setting the dedupe key
# after XADD avoids losing a message if XADD fails. The script itself is atomic.
_PUBLISH_LUA = """
if redis.call('EXISTS', KEYS[2]) == 1 then
  return {'duplicate', ''}
end
local entry_id = redis.call('XADD', KEYS[1], '*', 'envelope', ARGV[1])
redis.call('SET', KEYS[2], ARGV[2])
return {'published', entry_id}
"""


class RedisStreamPublisher:
    """Redis Streams publisher with atomic idempotent publication semantics."""

    def __init__(
        self,
        *,
        redis_url: str,
        namespace: ProjectNamespace,
        client: Any | None = None,
        heartbeat_ttl_seconds: int = 60,
    ) -> None:
        if not redis_url:
            raise ValueError("redis_url is required for Redis mode")
        if heartbeat_ttl_seconds < 5:
            raise ValueError("heartbeat_ttl_seconds must be >= 5")
        self.namespace = namespace
        self.heartbeat_ttl_seconds = heartbeat_ttl_seconds
        if client is None:
            try:
                from redis import Redis
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise RuntimeError(
                    "Redis mode requires the optional distributed dependency: "
                    "pip install 'laclaugpt-data-collection[distributed]'"
                ) from exc
            client = Redis.from_url(redis_url, decode_responses=True)
        self.client = client

    def publish(self, stream: str, envelope: TaskEnvelope) -> PublishResult:
        if envelope.project_id != self.namespace.project_id:
            raise ValueError("envelope project_id does not match publisher namespace")
        stream_key = self.namespace.stream_key(stream)
        dedupe_key = self.namespace.redis_key("published", envelope.idempotency_key)
        outcome = self.client.eval(
            _PUBLISH_LUA,
            2,
            stream_key,
            dedupe_key,
            envelope.to_json(),
            envelope.message_id,
        )
        status, entry_id = _decode_eval_result(outcome)
        if status == "duplicate":
            return PublishResult(
                backend="redis",
                published=False,
                duplicate=True,
                message_id=envelope.message_id,
            )
        if status != "published":
            raise RuntimeError(f"unexpected Redis publish result: {status!r}")
        return PublishResult(
            backend="redis",
            published=True,
            message_id=envelope.message_id,
            stream_entry_id=entry_id or None,
        )

    def heartbeat(
        self,
        *,
        run_id: str,
        worker_id: str,
        status: str,
        current_task_id: str | None = None,
        metadata: Mapping[str, Primitive] | None = None,
    ) -> None:
        allowed = {"starting", "idle", "busy", "draining", "stopped", "error"}
        if status not in allowed:
            raise ValueError(f"unknown worker status: {status}")
        payload = {
            "schema_version": "1.0",
            "project_id": self.namespace.project_id,
            "run_id": run_id,
            "worker_id": worker_id,
            "worker_role": "collection",
            "status": status,
            "current_task_id": current_task_id,
            "updated_at": datetime.now(UTC).isoformat(),
            "metadata": dict(metadata or {}),
        }
        self.client.setex(
            self.namespace.worker_key("collection", worker_id),
            self.heartbeat_ttl_seconds,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )


def publisher_from_environment(
    *,
    project_id: str,
    backend: Literal["direct", "redis"] = "direct",
    redis_prefix: str = "laclaugpt",
    client: Any | None = None,
) -> Publisher:
    """Create a publisher without importing Redis unless Redis mode is selected.

    The Redis connection is intentionally accepted only through
    ``LACLAUGPT_REDIS_URL`` at runtime. Public config may name the environment
    variable, but should never contain its value.
    """
    if backend == "direct":
        return DirectPublisher()
    redis_url = os.environ.get("LACLAUGPT_REDIS_URL", "")
    if not redis_url:
        raise RuntimeError("Redis mode requires LACLAUGPT_REDIS_URL")
    return RedisStreamPublisher(
        redis_url=redis_url,
        namespace=ProjectNamespace(project_id, redis_prefix=redis_prefix),
        client=client,
    )


def _decode_eval_result(value: Any) -> tuple[str, str]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise RuntimeError(f"invalid Redis script result: {value!r}")
    first, second = value
    if isinstance(first, bytes):
        first = first.decode("utf-8")
    if isinstance(second, bytes):
        second = second.decode("utf-8")
    return str(first), str(second)
