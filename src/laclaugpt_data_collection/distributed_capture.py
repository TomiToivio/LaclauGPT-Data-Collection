"""Distributed mirror for canonical browser captures.

MongoDB is durable canonical record state, S3/Allas stores raw capture objects,
and Redis carries only lightweight coordination references. Local CollectionStore
persistence remains in place as a recovery/debug fallback during the pilot.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import Settings
from .deployment import validate_profile
from .models import CanonicalRecord, CollectionProvenance
from .storage.remote import MongoRecordStore, RedisCoordinator, S3ObjectStore


class DistributedCaptureSink:
    """Mirror one canonical collection record into the shared distributed plane."""

    def __init__(self, settings: Settings) -> None:
        problems = validate_profile(settings)
        if problems:
            raise ValueError("invalid distributed configuration: " + "; ".join(problems))
        if not settings.distributed_requested:
            raise ValueError("distributed capture sink requires distributed backends")

        self.settings = settings
        namespace = settings.distributed_namespace
        self.records = MongoRecordStore(
            settings.mongodb_uri,
            settings.mongodb_database,
            collection=namespace.mongo_collection("records"),
            project_id=settings.project_id,
        )
        self.objects = S3ObjectStore(
            bucket=settings.s3_bucket,
            endpoint_url=settings.effective_s3_endpoint,
            region_name=settings.s3_region,
            access_key_id=settings.effective_s3_access_key,
            secret_access_key=settings.effective_s3_secret_key,
            prefix=f"{settings.s3_prefix_root}/{settings.project_id}",
        )
        self.redis = RedisCoordinator(settings.redis_url, namespace)

    def assert_private_config(self, study_config: str | Path) -> Path:
        """Fail closed unless distributed study config comes from the private root."""
        private_root = self.settings.private_config_dir
        if private_root is None:  # validate_profile should already reject this
            raise ValueError("LACLAUGPT_PRIVATE_CONFIG_DIR is required")
        root = private_root.expanduser().resolve()
        candidate = Path(study_config).expanduser().resolve()
        if not candidate.is_file():
            raise ValueError(f"study config does not exist: {candidate}")
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                "distributed study config must live below LACLAUGPT_PRIVATE_CONFIG_DIR"
            ) from exc
        return candidate

    def _raw_object(self, record: CanonicalRecord) -> str:
        payload = record.raw_capture.payload
        if payload is None:
            return record.raw_capture.ref or ""
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        key = f"runs/{self.settings.run_id}/raw/{digest}.json"
        uri = self.objects.put_bytes(key, encoded, content_type="application/json")
        record.raw_capture.checksum = f"sha256:{digest}"
        record.raw_capture.ref = uri
        return uri

    def ingest(self, record_data: dict[str, Any]) -> CanonicalRecord:
        """Persist idempotently and publish a lightweight collected-record event."""
        collection_id = str(record_data.get("collection_id") or self.settings.project_id)
        arena = str(record_data.get("arena") or "")
        canonical_data = {
            key: value
            for key, value in record_data.items()
            if key in CanonicalRecord.model_fields
        }
        record = CanonicalRecord.model_validate(canonical_data)
        raw_ref = self._raw_object(record)

        if not record.provenance:
            record.provenance.append(CollectionProvenance())
        for provenance in record.provenance:
            if not provenance.run_id:
                provenance.run_id = self.settings.run_id
            provenance.metadata.setdefault("project_id", self.settings.project_id)
            provenance.metadata.setdefault("collection_id", collection_id)
            if arena:
                provenance.metadata.setdefault("arena", arena)
            provenance.metadata.setdefault("machine", self.settings.machine)
            provenance.metadata.setdefault("execution", self.settings.execution)
        record.source.raw_metadata.setdefault("collection_id", collection_id)
        if arena:
            record.source.raw_metadata.setdefault("arena", arena)

        self.records.upsert(record)
        self.redis.publish_stream(
            "collected",
            {
                "project_id": self.settings.project_id,
                "collection_id": collection_id,
                "arena": arena,
                "run_id": self.settings.run_id,
                "source_url": record.source_url,
                "record_collection": self.settings.distributed_namespace.mongo_collection("records"),
                "raw_ref": raw_ref,
            },
        )
        return record

    def smoke_check(self) -> dict[str, str]:
        """Verify the control-plane dependencies without exposing credentials."""
        return {
            "project_id": self.settings.project_id,
            "run_id": self.settings.run_id,
            "redis": "ok" if self.redis.ping() else "failed",
            "mongodb_collection": self.settings.distributed_namespace.mongo_collection("records"),
            "s3_bucket": self.settings.s3_bucket,
            "s3_prefix": f"{self.settings.s3_prefix_root}/{self.settings.project_id}",
        }
