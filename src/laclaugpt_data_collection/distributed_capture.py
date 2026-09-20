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
from .handoff import build_handoff
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
            signature_version=settings.s3_signature_version,
            addressing_style=settings.s3_addressing_style,
        )
        self.redis = (
            RedisCoordinator(settings.redis_url, namespace)
            if settings.messaging_backend == "redis"
            else None
        )
        self.notification_errors: list[str] = []

    def assert_private_config(self, study_config: str | Path) -> Path:
        """Require distributed study config to live in an ignored runtime config root.

        ``LACLAUGPT_PRIVATE_CONFIG_DIR`` remains the explicit private root.  The
        repository's documented ``data/config`` directory is also accepted because
        the whole ``data/`` tree is gitignored and is the standard localhost runtime
        location used by the AI26 setup guide and wrappers.
        """
        private_root = self.settings.private_config_dir
        if private_root is None:  # validate_profile should already reject this
            raise ValueError("LACLAUGPT_PRIVATE_CONFIG_DIR is required")

        candidate = Path(study_config).expanduser().resolve()
        if not candidate.is_file():
            raise ValueError(f"study config does not exist: {candidate}")

        roots = {
            private_root.expanduser().resolve(),
            self.settings.data_path("config").expanduser().resolve(),
        }
        for root in roots:
            try:
                candidate.relative_to(root)
                return candidate
            except ValueError:
                continue

        allowed = ", ".join(str(root) for root in sorted(roots, key=str))
        raise ValueError(
            "distributed study config must live below an ignored runtime config root "
            f"(LACLAUGPT_PRIVATE_CONFIG_DIR or data/config); allowed roots: {allowed}"
        )

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

    def _publish(self, name: str, fields: dict[str, Any]) -> None:
        """Publish best-effort coordination after durable persistence.

        Redis messaging is optional in Phase 1. A missing or failed event must never
        invalidate a record that MongoDB has already accepted; Analysis can recover
        by polling the durable record collection.
        """
        if self.redis is None:
            return
        try:
            self.redis.publish_stream(name, fields)
        except Exception as exc:  # coordination failure is non-fatal by contract
            self.notification_errors.append(f"{name}: {exc}")

    def ingest(self, record_data: dict[str, Any]) -> CanonicalRecord:
        """Persist idempotently and publish lightweight collection/handoff events."""
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
        common = {
            "project_id": self.settings.project_id,
            "collection_id": collection_id,
            "arena": arena,
            "run_id": self.settings.run_id,
            "source_url": record.source_url,
            "record_collection": self.settings.distributed_namespace.mongo_collection("records"),
        }
        self._publish("collected", {**common, "raw_ref": raw_ref})

        handoff = build_handoff(
            record.model_dump(mode="json"),
            project_id=self.settings.project_id,
            run_id=self.settings.run_id,
        )
        if handoff["status"] == "ready":
            self._publish(
                "analysis-ready",
                {
                    **common,
                    "handoff_key": str(handoff["handoff_key"]),
                    "revision": str(handoff["revision"]),
                    "published_at": str(handoff.get("published_at") or ""),
                    "source_priority": str(handoff["source_priority"]),
                },
            )
        return record

    def smoke_check(self) -> dict[str, str]:
        """Verify the control-plane dependencies without exposing credentials."""
        return {
            "project_id": self.settings.project_id,
            "run_id": self.settings.run_id,
            "redis": (
                "disabled"
                if self.redis is None
                else ("ok" if self.redis.ping() else "failed")
            ),
            "mongodb_collection": self.settings.distributed_namespace.mongo_collection("records"),
            "s3_bucket": self.settings.s3_bucket,
            "s3_prefix": f"{self.settings.s3_prefix_root}/{self.settings.project_id}",
        }
