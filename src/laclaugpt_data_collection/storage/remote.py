"""Optional distributed backends.

Dependencies are imported lazily so local-only installations stay lightweight.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..models import NormalizedRecord


class MongoRecordStore:
    def __init__(self, uri: str, database: str, collection: str = "records") -> None:
        try:
            from pymongo import MongoClient
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install laclaugpt-data-collection[distributed] for MongoDB") from exc
        self._client = MongoClient(uri)
        self._collection = self._client[database][collection]
        self._collection.create_index(
            [("platform", 1), ("document_id", 1)], unique=True, name="platform_document_id"
        )

    def upsert(self, record: NormalizedRecord) -> None:
        payload = record.model_dump(mode="json")
        self._collection.replace_one(
            {"platform": record.platform, "document_id": record.document_id},
            payload,
            upsert=True,
        )

    def upsert_many(self, records: Iterable[NormalizedRecord]) -> None:
        try:
            from pymongo import ReplaceOne
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install laclaugpt-data-collection[distributed] for MongoDB") from exc
        operations = [
            ReplaceOne(
                {"platform": record.platform, "document_id": record.document_id},
                record.model_dump(mode="json"),
                upsert=True,
            )
            for record in records
        ]
        if operations:
            self._collection.bulk_write(operations, ordered=False)

    def contains(self, platform: str, document_id: str) -> bool:
        return (
            self._collection.find_one(
                {"platform": platform, "document_id": document_id}, {"_id": 1}
            )
            is not None
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
    ) -> None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install laclaugpt-data-collection[distributed] for S3") from exc
        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region_name or None,
            aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
        )

    def put_bytes(self, key: str, payload: bytes, *, content_type: str = "application/octet-stream") -> str:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=payload, ContentType=content_type)
        return f"s3://{self.bucket}/{key}"

    def put_text(self, key: str, payload: str, *, content_type: str = "text/plain; charset=utf-8") -> str:
        return self.put_bytes(key, payload.encode("utf-8"), content_type=content_type)


class RedisCoordinator:
    """Small coordination/cache facade, never the canonical research record store."""

    def __init__(self, url: str) -> None:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install laclaugpt-data-collection[distributed] for Redis") from exc
        self._client = redis.Redis.from_url(url, decode_responses=True)

    def ping(self) -> bool:
        return bool(self._client.ping())

    def acquire_once(self, key: str, *, ttl_seconds: int = 3600) -> bool:
        return bool(self._client.set(f"laclaugpt:lock:{key}", "1", nx=True, ex=ttl_seconds))

    def set_json(self, key: str, payload: str, *, ttl_seconds: int | None = None) -> None:
        self._client.set(f"laclaugpt:cache:{key}", payload, ex=ttl_seconds)

    def get(self, key: str) -> Any:
        return self._client.get(f"laclaugpt:cache:{key}")
