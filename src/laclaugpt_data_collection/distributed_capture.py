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

HOLLOW_RECORD_REASON = "hollow_record"


class HollowRecordError(ValueError):
    """A capture that carried only a source URL, raised at the persistence boundary.

    Issue #322: 1,703 rows reached `ai26__records` with a real X post URL and nothing
    else because the writer that accepted them had no way to say no. The evidence rule
    itself lives at the raise site in :meth:`DistributedCaptureSink.ingest_with_status`,
    which every writer goes through (Firefox mirror, JSONL sync, Laskin phase 1, browser
    server).

    Subclassing ``ValueError`` keeps existing callers that treat a refused write as a
    value error working. The added fields are what make the refusal *reportable*: a
    caller can name the source it was reading and the URL in its per-source report,
    instead of surfacing a bare "hollow capture" line that no reader can trace back to
    a source.
    """

    def __init__(
        self, *, source: str = "", source_url: str = "", collection_id: str = ""
    ) -> None:
        self.reason = HOLLOW_RECORD_REASON
        self.source = source or "<unnamed>"
        self.source_url = source_url
        self.collection_id = collection_id
        # The URL goes first and the message stays short on purpose: per-line and
        # per-source reports truncate the text (180 characters in `distributed-sync`),
        # and a refusal whose URL was cut off cannot be traced back to the row.
        super().__init__(
            f"refusing hollow capture: {source_url or '<no source_url>'} has no text, "
            "raw payload/ref or media; source_url alone is not a collected record "
            f"(source {self.source!r}, collection {collection_id or 'unknown'})"
        )


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
        """Persist idempotently and publish lightweight collection/handoff events.

        Returns the canonical record. Callers that must distinguish a new
        document from a re-write should use :meth:`ingest_with_status`
        (issue #222).
        """
        record, _ = self.ingest_with_status(record_data)
        return record

    def ingest_with_status(
        self, record_data: dict[str, Any]
    ) -> tuple[CanonicalRecord, bool]:
        """Persist one record; return ``(record, created)``.

        ``created`` is True when the store held no document for this identity
        before the write. Issue #222: a cycle must distinguish corpus growth
        (``created``) from sync operations (every write), because RSS re-emits
        its current window hourly and the raw upsert count over-reports growth.
        """
        collection_id = str(record_data.get("collection_id") or self.settings.project_id)
        arena = str(record_data.get("arena") or "")
        canonical_data = {
            key: value
            for key, value in record_data.items()
            if key in CanonicalRecord.model_fields
        }
        record = CanonicalRecord.model_validate(canonical_data)
        # #322: refuse URL-only placeholders before touching S3, Mongo or Redis.
        has_text = bool((record.content.text or "").strip())
        has_raw = record.raw_capture.preserved
        has_media = bool(record.content.media_references or record.content.file_references)
        if not (has_text or has_raw or has_media):
            raise HollowRecordError(
                # Name the configured source when the record knows one, otherwise the
                # collection: a platform-less row has nothing else to identify it by.
                source=str(record.source.platform or "") or collection_id,
                source_url=str(record.source_url or ""),
                collection_id=collection_id,
            )
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

        created = self.records.upsert(record)
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
        return record, created

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
