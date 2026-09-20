"""MongoDB document + lightweight graph + vector-capable record backend."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..handoff import build_handoff
from ..models import CanonicalRecord, canonicalize_source_url
from .remote import _routing_metadata, _run_id


class MongoRecordStore:
    """Canonical MongoDB persistence with bounded graph helpers.

    Data Collection preserves graph/vector enrichment but does not require or
    generate it. Downstream modules may write graph references under
    ``analysis.relationships`` and embeddings under ``analysis.embeddings``.
    """

    def __init__(
        self,
        uri: str,
        database: str,
        collection: str,
        project_id: str,
        *,
        connect_timeout_ms: int = 2000,
        graph_max_depth: int = 3,
        client_factory: Any | None = None,
    ) -> None:
        if not uri:
            raise RuntimeError("MongoDB URI is required")
        if client_factory is None:
            try:
                from pymongo import MongoClient
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError(
                    "Install laclaugpt-data-collection[distributed] for MongoDB"
                ) from exc
            client_factory = MongoClient
        self.project_id = project_id
        self.graph_max_depth = max(0, graph_max_depth)
        self._client = client_factory(uri, serverSelectionTimeoutMS=connect_timeout_ms)
        self._database = self._client[database]
        self._collection = self._database[collection]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        self._collection.create_index(
            [("project_id", 1), ("collection_id", 1), ("source_url", 1)],
            unique=True,
            name="routing_source_unique",
        )
        self._collection.create_index([("project_id", 1)], name="project_id")
        self._collection.create_index([("collection_id", 1)], name="collection_id")
        self._collection.create_index([("arena", 1)], name="arena")
        self._collection.create_index(
            [("analysis.relationships.targets", 1)], name="relationship_targets"
        )
        self._collection.create_index(
            [("analysis.embeddings.model", 1)], name="embedding_model"
        )

    def ping(self) -> bool:
        self._client.admin.command("ping")
        return True

    def capabilities(self) -> dict[str, Any]:
        """Expose available features without making vector search a requirement."""
        info: dict[str, Any] = {"mongodb": True, "graph_lookup": True, "vector_search": False}
        try:
            build = self._database.command("buildInfo")
            version = str(build.get("version", ""))
            info["version"] = version
            # Native vector search depends on deployment/tier/index configuration.
            # Presence is therefore reported conservatively and can be overridden by
            # downstream feature detection rather than assumed from version alone.
            info["vector_search"] = False
        except Exception:
            info["version"] = "unknown"
        return info

    def _payload(self, record: CanonicalRecord) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        collection_id, arena = _routing_metadata(record, self.project_id)
        payload["project_id"] = self.project_id
        payload["collection_id"] = collection_id
        payload["arena"] = arena
        payload["handoff"] = build_handoff(
            payload, project_id=self.project_id, run_id=_run_id(record)
        )
        return payload

    def _query(self, record: CanonicalRecord) -> dict[str, str]:
        collection_id, _ = _routing_metadata(record, self.project_id)
        return {
            "source_url": record.source_url,
            "project_id": self.project_id,
            "collection_id": collection_id,
        }

    def upsert(self, record: CanonicalRecord) -> None:
        self._collection.replace_one(self._query(record), self._payload(record), upsert=True)

    def upsert_many(self, records: Iterable[CanonicalRecord]) -> None:
        try:
            from pymongo import ReplaceOne
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install laclaugpt-data-collection[distributed] for MongoDB") from exc
        operations = [
            ReplaceOne(self._query(record), self._payload(record), upsert=True)
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
        """Return a bounded set of canonical records with unresolved media refs.

        This is the cross-machine discovery path for media workers.  It reads the
        shared canonical MongoDB collection, so a Laskin worker can discover media
        references produced by a laptop-only browser capture without depending on
        the laptop's local JSONL files or a Redis task queue.
        """
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

    def graph_lookup(
        self,
        source_url: str,
        *,
        max_depth: int | None = None,
        relationship_path: str = "analysis.relationships.targets",
    ) -> list[dict[str, Any]]:
        """Traverse URI references in the same canonical collection using $graphLookup."""
        depth = self.graph_max_depth if max_depth is None else max(0, min(max_depth, self.graph_max_depth))
        pipeline = [
            {"$match": {"project_id": self.project_id, "source_url": canonicalize_source_url(source_url)}},
            {
                "$graphLookup": {
                    "from": self._collection.name,
                    "startWith": f"${relationship_path}",
                    "connectFromField": relationship_path,
                    "connectToField": "source_url",
                    "as": "related_records",
                    "maxDepth": depth,
                    "depthField": "graph_depth",
                    "restrictSearchWithMatch": {"project_id": self.project_id},
                }
            },
        ]
        return list(self._collection.aggregate(pipeline))

    @staticmethod
    def from_document(document: dict[str, Any]) -> CanonicalRecord:
        return CanonicalRecord.model_validate(
            {
                key: value
                for key, value in document.items()
                if key not in {"_id", "project_id", "collection_id", "arena", "handoff"}
            }
        )
