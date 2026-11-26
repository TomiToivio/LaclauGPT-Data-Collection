"""MongoDB document + lightweight graph + vector-capable record backend."""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from ..handoff import build_handoff
from ..models import CanonicalRecord, source_identity
from .remote import _carry_forward_media_state, _routing_metadata, _run_id


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
        # #478: cross-machine identity. The raw source_url is evidence and differs between hosts
        # (`twitter.com/...?s=20` and `x.com/...` are the same post), so uniqueness is enforced on the
        # canonical identity instead. Partial, because documents written before the field existed must keep
        # loading until the backfill has run.
        self._collection.create_index(
            [("project_id", 1), ("collection_id", 1), ("source_identity", 1)],
            unique=True,
            name="routing_identity_unique",
            partialFilterExpression={"source_identity": {"$type": "string"}},
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
        # Derived, never the evidence: `source_url` stays exactly as captured, while identity is what two
        # machines, a retry and an x.com/twitter.com spelling must agree on (#478).
        payload["source_identity"] = source_identity(record.source_url)
        payload["collection_id"] = collection_id
        payload["arena"] = arena
        payload["handoff"] = build_handoff(
            payload, project_id=self.project_id, run_id=_run_id(record)
        )
        return payload

    def _query(self, record: CanonicalRecord) -> dict[str, str]:
        collection_id, _ = _routing_metadata(record, self.project_id)
        return {
            "source_identity": source_identity(record.source_url),
            "project_id": self.project_id,
            "collection_id": collection_id,
        }

    def _legacy_query(self, record: CanonicalRecord) -> dict[str, str]:
        """How documents written before identity existed are found: by their raw URL."""
        collection_id, _ = _routing_metadata(record, self.project_id)
        return {
            "source_url": record.source_url,
            "project_id": self.project_id,
            "collection_id": collection_id,
        }

    def _status_id(self, url: str) -> str:
        match = re.search(r"/status(?:es)?/(\d+)", url or "")
        return match.group(1) if match else ""

    def _existing(self, record: CanonicalRecord) -> tuple[dict[str, Any] | None, bool]:
        """The stored document for this record, whichever generation of key it was written under.

        A legacy document is returned as *existing*, so the first re-ingest of an old URL adopts it (and
        stamps the identity) instead of inserting a second copy -- the failure mode a URL-variant fix creates
        if it only changes new writes.
        """
        found = self._collection.find_one(self._query(record))
        if found is not None:
            return found, True
        if found is None:
            found = self._collection.find_one(self._legacy_query(record))
        if found is None:
            # The store already holds X documents written under an earlier spelling of the URL
            # (`x.com/<user>/status/<id>`). Their identity was never stamped, so find them by the post id --
            # the one part of the URL that is the post rather than the path a machine happened to hold.
            status_id = self._status_id(record.source_url)
            if status_id:
                collection_id, _ = _routing_metadata(record, self.project_id)
                found = self._collection.find_one(
                    {
                        "project_id": self.project_id,
                        "collection_id": collection_id,
                        "source_identity": {"$exists": False},
                        "source_url": {"$regex": f"/status(?:es)?/{status_id}(?:/|$)"},
                    }
                )
        return found, False

    def upsert(self, record: CanonicalRecord) -> bool:
        """Persist one record; return True when it was newly created (issue #222).

        Carries resolved media back-references forward so a re-ingest cannot wipe
        an ``object_ref`` the media worker already wrote (issue #210).
        """
        existing, matched_by_identity = self._existing(record)
        payload = self._payload(record)
        if existing:
            _carry_forward_media_state(payload, existing)
            if not matched_by_identity and "_id" in existing:
                # Adopt a document written before identity existed: replace *that document* by its own key, so
                # the first re-ingest after this change updates it instead of inserting a second copy. The
                # payload carries the identity, so the next write matches by identity.
                self._collection.replace_one({"_id": existing["_id"]}, payload, upsert=True)
                return False
        self._collection.replace_one(self._query(record), payload, upsert=True)
        return existing is None

    def upsert_many(self, records: Iterable[CanonicalRecord]) -> None:
        try:
            from pymongo import ReplaceOne
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install laclaugpt-data-collection[distributed] for MongoDB") from exc
        batch = list(records)
        # #478: the bulk path honours the same identity as the single-document path. Documents written
        # before the identity field existed are adopted first, by their raw URL, so a bulk re-ingest cannot
        # create a second copy of a post that is already stored under the old key.
        self._adopt_legacy_documents(batch)
        operations = [
            ReplaceOne(self._query(record), self._payload(record), upsert=True)
            for record in batch
        ]
        if operations:
            self._collection.bulk_write(operations, ordered=False)

    def _adopt_legacy_documents(self, records: Iterable[CanonicalRecord]) -> int:
        """Stamp the identity on documents stored under their raw URL before a bulk write (#478).

        Only documents that lack the field are touched, and only their routing key: the captured URL, content
        and provenance stay as they were. Returns the number adopted.
        """
        raw_urls = sorted({record.source_url for record in records if record.source_url})
        if not raw_urls:
            return 0
        adopted = 0
        for document in self._collection.find(
            {
                "project_id": self.project_id,
                "source_url": {"$in": raw_urls},
                "source_identity": {"$exists": False},
            },
            {"_id": 1, "source_url": 1},
        ):
            self._collection.update_one(
                {"_id": document["_id"]},
                {"$set": {"source_identity": source_identity(str(document.get("source_url") or ""))}},
            )
            adopted += 1
        return adopted

    def contains(self, source_url: str, *, collection_id: str | None = None) -> bool:
        identity = source_identity(source_url)
        query: dict[str, Any] = {"source_identity": identity, "project_id": self.project_id}
        if collection_id:
            query["collection_id"] = collection_id
        return self._collection.find_one(query, {"_id": 1}) is not None

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
            {"$match": {"project_id": self.project_id, "source_identity": source_identity(source_url)}},
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
                if key not in {"_id", "project_id", "collection_id", "arena", "handoff", "source_identity"}
            }
        )
