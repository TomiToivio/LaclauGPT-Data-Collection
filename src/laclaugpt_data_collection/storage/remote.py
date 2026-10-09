"""Optional distributed backends for canonical Collection records."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..distributed import ProjectNamespace
from ..handoff import build_handoff
from ..models import CanonicalRecord, canonicalize_source_url


def _routing_metadata(record: CanonicalRecord, project_id: str) -> tuple[str, str]:
    """Read collection/arena routing metadata without making it analysis truth."""
    collection_id = ""
    arena = ""
    if record.provenance:
        metadata = record.provenance[-1].metadata
        collection_id = str(metadata.get("collection_id") or "")
        arena = str(metadata.get("arena") or "")
    collection_id = collection_id or str(record.source.raw_metadata.get("collection_id") or "")
    arena = arena or str(record.source.raw_metadata.get("arena") or "")
    return collection_id or project_id, arena


def _run_id(record: CanonicalRecord) -> str:
    if record.provenance:
        return str(record.provenance[-1].run_id or "")
    return ""


def _carry_forward_media_state(
    incoming: dict[str, Any], existing: Mapping[str, Any]
) -> None:
    """Copy resolved media back-references from a stored document into new payload.

    Issue #210: ``replace_one`` is a full-document replace, so a re-ingest that
    carries an empty ``object_ref`` would discard a pointer the media worker had
    already resolved. The object is still in the durable media index, but the
    downloader treats the terminal ``completed`` status as "nothing to do", so
    nothing would ever restore the pointer. Carrying it forward on every write
    stops the loss recurring; ``repair_media_references`` fixes refs already lost.

    Matching is on ``(media_index, url)`` so a shifted position cannot attach the
    wrong object. A ref the incoming record has genuinely dropped stays dropped.
    """
    def _refs(container: Any) -> list[dict[str, Any]]:
        if not isinstance(container, dict):
            return []
        refs = container.get("media_references")
        return [r for r in refs if isinstance(r, dict)] if isinstance(refs, list) else []

    incoming_refs = _refs(incoming.get("content"))
    if not incoming_refs:
        return
    stored_by_key: dict[tuple[int, str], dict[str, Any]] = {}
    for ref in _refs((existing or {}).get("content")):
        key = (int(ref.get("media_index", -1)), str(ref.get("url") or ""))
        if str(ref.get("object_ref") or ""):
            stored_by_key[key] = ref
    for position, ref in enumerate(incoming_refs):
        if str(ref.get("object_ref") or ""):
            continue
        prior = stored_by_key.get((int(ref.get("media_index", position)), str(ref.get("url") or "")))
        if prior is None:
            continue
        ref["object_ref"] = str(prior.get("object_ref") or "")
        if prior.get("checksum"):
            ref["checksum"] = str(prior["checksum"])
        prior_meta = prior.get("metadata")
        if isinstance(prior_meta, dict):
            metadata = ref.setdefault("metadata", {})
            for field in ("byte_size", "mime_type", "download_status"):
                if field in prior_meta and field not in metadata:
                    metadata[field] = prior_meta[field]
            metadata["carried_forward_from_prior_ingest"] = True


class MongoRecordStore:
    def __init__(
        self,
        uri: str,
        database: str,
        collection: str,
        project_id: str,
    ) -> None:
        try:
            from pymongo import MongoClient
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install laclaugpt-data-collection[distributed] for MongoDB") from exc
        self.project_id = project_id
        self._client = MongoClient(uri)
        self._collection = self._client[database][collection]
        # Old pilot builds used source_url alone as a unique key. That prevents a
        # shared runtime from preserving the same public source in two studies.
        try:
            if "source_url_unique" in self._collection.index_information():
                self._collection.drop_index("source_url_unique")
        except (AttributeError, TypeError):  # pragma: no cover - simple fakes/mocks
            pass
        self._collection.create_index(
            [("project_id", 1), ("collection_id", 1), ("source_url", 1)],
            unique=True,
            name="routing_source_unique",
        )
        self._collection.create_index([("project_id", 1)], name="project_id")
        self._collection.create_index([("collection_id", 1)], name="collection_id")
        self._collection.create_index([("arena", 1)], name="arena")
        self._collection.create_index(
            [
                ("handoff.status", 1),
                ("handoff.source_priority", 1),
                ("handoff.published_at", -1),
                ("source_url", 1),
            ],
            name="analysis_ready_order",
        )
        self._collection.create_index(
            [("handoff.handoff_key", 1)],
            name="handoff_key",
        )

    def _payload(self, record: CanonicalRecord) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        collection_id, arena = _routing_metadata(record, self.project_id)
        payload["project_id"] = self.project_id
        payload["collection_id"] = collection_id
        payload["arena"] = arena
        payload["handoff"] = build_handoff(
            payload,
            project_id=self.project_id,
            run_id=_run_id(record),
        )
        return payload

    def _query(self, record: CanonicalRecord) -> dict[str, str]:
        collection_id, _ = _routing_metadata(record, self.project_id)
        return {
            "source_url": record.source_url,
            "project_id": self.project_id,
            "collection_id": collection_id,
        }

    def upsert(self, record: CanonicalRecord) -> bool:
        """Persist one record; return True when it was newly created (issue #222).

        ``replace_one(..., upsert=True)`` collapses a re-sync onto the existing
        document, so the write is idempotent but the caller cannot tell a new
        document from a re-write. The collection cycle needs exactly that
        distinction to report corpus growth rather than sync operations.

        It also replaces the whole document, which is how issue #210 lost media
        back-references: a re-ingest of a record whose object was already
        downloaded came back with ``object_ref == ""`` and the durable media
        index then skipped the repair as "already complete". So the payload
        carries forward any ``object_ref``/``checksum`` the stored document had
        for the same media ref, before writing.

        Resolution: read the existing document once, merge media state into the
        payload, write, and report whether the document was newly created. The
        ``source_url``/``project_id``/``collection_id`` triple is unique by index,
        and this is a single-machine collector, so the read-then-write is not a
        correctness race (a concurrent duplicate would still land one document;
        the return value is a metric, not a concurrency guarantee).
        """
        existing = self._collection.find_one(self._query(record))
        payload = self._payload(record)
        if existing:
            _carry_forward_media_state(payload, existing)
        self._collection.replace_one(
            self._query(record),
            payload,
            upsert=True,
        )
        return existing is None

    def upsert_many(self, records: Iterable[CanonicalRecord]) -> None:
        try:
            from pymongo import ReplaceOne
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install laclaugpt-data-collection[distributed] for MongoDB") from exc
        operations = [
            ReplaceOne(
                self._query(record),
                self._payload(record),
                upsert=True,
            )
            for record in records
        ]
        if operations:
            self._collection.bulk_write(operations, ordered=False)

    def contains(self, source_url: str, *, collection_id: str | None = None) -> bool:
        identity = canonicalize_source_url(source_url)
        query: dict[str, Any] = {"source_url": identity, "project_id": self.project_id}
        if collection_id:
            query["collection_id"] = collection_id
        return self._collection.find_one(query, {"_id": 1}) is not None

    def pending_media_records(
        self,
        *,
        collection_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return a bounded set of canonical records with unresolved media refs."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        query: dict[str, Any] = {
            "project_id": self.project_id,
            "content.media_references": {
                "$elemMatch": {
                    "url": {"$exists": True, "$ne": ""},
                    "$or": [
                        {"object_ref": {"$exists": False}},
                        {"object_ref": ""},
                    ],
                }
            },
        }
        if collection_id:
            query["collection_id"] = collection_id
        cursor = self._collection.find(query).limit(limit)
        return [
            {
                key: value
                for key, value in document.items()
                if key not in {"_id", "handoff"}
            }
            for document in cursor
        ]

    @staticmethod
    def from_document(document: dict[str, Any]) -> CanonicalRecord:
        """Reconstruct canonical semantics without backend routing/handoff metadata."""
        return CanonicalRecord.model_validate(
            {
                key: value
                for key, value in document.items()
                if key not in {"_id", "project_id", "collection_id", "arena", "handoff"}
            }
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
        signature_version: str = "s3",
        addressing_style: str = "auto",
    ) -> None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install laclaugpt-data-collection[distributed] for S3") from exc
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.signature_version = signature_version
        self.addressing_style = addressing_style
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region_name or None,
            aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
            config=Config(
                signature_version=signature_version,
                s3={"addressing_style": addressing_style},
            ),
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
