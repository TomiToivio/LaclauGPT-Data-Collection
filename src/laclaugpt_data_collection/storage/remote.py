"""Optional distributed backends for canonical Collection records."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..distributed import ProjectNamespace
from ..models import CanonicalRecord, canonicalize_source_url


class MongoRecordStore:
    def __init__(self, uri: str, database: str, collection: str) -> None:
        try:
            from pymongo import MongoClient
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install laclaugpt-data-collection[distributed] for MongoDB") from exc
        self._client = MongoClient(uri)
        self._collection = self._client[database][collection]
        self._collection.create_index([("source_url", 1)], unique=True, name="source_url_unique")

    def upsert(self, record: CanonicalRecord) -> None:
        payload = record.model_dump(mode="json")
        self._collection.replace_one(
            {"source_url": record.source_url},
            payload,
            upsert=True,
        )

    def upsert_many(self, records: Iterable[CanonicalRecord]) -> None:
        try:
            from pymongo import ReplaceOne
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install laclaugpt-data-collection[distributed] for MongoDB") from exc
        operations = [
            ReplaceOne(
                {"source_url": record.source_url},
                record.model_dump(mode="json"),
                upsert=True,
            )
            for record in records
        ]
        if operations:
            self._collection.bulk_write(operations, ordered=False)

    def contains(self, source_url: str) -> bool:
        identity = canonicalize_source_url(source_url)
        return self._collection.find_one({"source_url": identity}, {"_id": 1}) is not None

    @staticmethod
    def from_document(document: dict[str, Any]) -> CanonicalRecord:
        """Reconstruct canonical semantics without treating Mongo `_id` as identity."""
        return CanonicalRecord.model_validate(
            {key: value for key, value in document.items() if key != "_id"}
        )


class S3ObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region_name: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        prefix: str = "",
    ) -> None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install laclaugpt-data-collection[distributed] for S3") from exc
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region_name or None,
            aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
        )

    def _key(self, key: str) -> str:
        clean = key.lstrip("/")
        return f"{self.prefix}/{clean}" if self.prefix else clean

    def put_bytes(
        self,
        key: str,
        payload: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> str:
        resolved = self._key(key)
        self._client.put_object(
            Bucket=self.bucket,
            Key=resolved,
            Body=payload,
            ContentType=content_type,
        )
        return f"s3://{self.bucket}/{resolved}"

    def put_text(
        self,
        key: str,
        payload: str,
        *,
        content_type: str = "text/plain; charset=utf-8",
    ) -> str:
        return self.put_bytes(key, payload.encode("utf-8"), content_type=content_type)


class RedisCoordinator:
    """Project-scoped coordination and control-plane facade."""

    def __init__(self, url: str, namespace: ProjectNamespace) -> None:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install laclaugpt-data-collection[distributed] for Redis") from exc
        self._client = redis.Redis.from_url(url, decode_responses=True)
        self.namespace = namespace

    def ping(self) -> bool:
        return bool(self._client.ping())

    def acquire_once(self, resource: str, *, ttl_seconds: int = 3600) -> bool:
        key = self.namespace.redis_key("lock", resource)
        return bool(self._client.set(key, "1", nx=True, ex=ttl_seconds))

    def set_json(self, name: str, payload: str, *, ttl_seconds: int | None = None) -> None:
        self._client.set(self.namespace.redis_key("cache", name), payload, ex=ttl_seconds)

    def get(self, name: str) -> Any:
        return self._client.get(self.namespace.redis_key("cache", name))

    def set_control_document(
        self,
        key: str,
        payload: str,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        if not key.startswith(f"{self.namespace.redis_base}:"):
            raise ValueError("control document key is outside the configured project namespace")
        self._client.set(key, payload, ex=ttl_seconds)

    def get_control_document(self, key: str) -> str | None:
        if not key.startswith(f"{self.namespace.redis_base}:"):
            raise ValueError("control document key is outside the configured project namespace")
        return self._client.get(key)

    def publish_stream(
        self,
        name: str,
        fields: Mapping[str, str],
        *,
        maxlen: int = 100000,
    ) -> str:
        return str(
            self._client.xadd(
                self.namespace.stream_key(name),
                dict(fields),
                maxlen=maxlen,
                approximate=True,
            )
        )
