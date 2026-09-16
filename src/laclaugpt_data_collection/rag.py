"""Optional, failure-tolerant hooks for graph/vector RAG indexing.

Collection remains authoritative for acquisition and canonical persistence. This
module only exports graph-ready factual/source metadata and invokes an optional
indexer after storage has succeeded. It intentionally contains no Neo4j or Ollama
hard dependency.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .models import CanonicalRecord

logger = logging.getLogger(__name__)

ANALYSIS_ONLY_RELATIONS = {
    "ARTICULATED_WITH",
    "EMPTY_SIGNIFIER",
    "ANTAGONISTIC_TO",
    "IDEOLOGICAL_FORMATION",
}


@dataclass(frozen=True)
class IndexResult:
    status: str
    record_id: str
    idempotency_key: str
    error: str = ""


class RecordIndexer(Protocol):
    """Minimal adapter implemented by Neo4j/vector/queue integrations."""

    def index(self, payload: dict[str, Any], *, idempotency_key: str) -> None: ...


def graph_ready_payload(record: CanonicalRecord, *, dataset: str = "") -> dict[str, Any]:
    """Return source-factual metadata safe for downstream semantic indexing.

    The payload is deliberately restricted to collection-owned facts and provenance.
    No discourse-theoretical relations are inferred here.
    """
    provenance = [item.model_dump(mode="json") for item in record.provenance]
    latest = provenance[-1] if provenance else {}
    source = record.source
    return {
        "schema_version": record.schema_version,
        "record_id": record.source_url,
        "source_url": record.source_url,
        "source_native_ids": dict(record.source_native_ids),
        "dataset": dataset,
        "platform": source.platform,
        "source_type": source.source_type,
        "language": source.language or record.content.language or "",
        "created_at": source.created_at,
        "collected_at": source.collected_at or latest.get("captured_at"),
        "collector": source.collector or latest.get("collector", "laclaugpt-data-collection"),
        "collector_version": latest.get("collector_version", ""),
        "collection_method": source.collection_method,
        "raw_ref": record.raw_capture.ref or source.raw_ref,
        "raw_checksum": record.raw_capture.checksum,
        "raw_metadata": dict(source.raw_metadata),
        "provenance": provenance,
        "privacy": dict(record.review.get("privacy", {})) if isinstance(record.review, dict) else {},
        "content": {
            "title": record.content.title,
            "text": record.content.text,
            "media_references": [item.model_dump(mode="json") for item in record.content.media_references],
        },
        "factual_relations": [
            {"type": "ON_PLATFORM", "target": source.platform} if source.platform else None,
            {"type": "IN_DATASET", "target": dataset} if dataset else None,
            {"type": "HAS_LANGUAGE", "target": source.language or record.content.language}
            if (source.language or record.content.language)
            else None,
        ],
    } | {
        "factual_relations": [
            relation
            for relation in [
                {"type": "ON_PLATFORM", "target": source.platform} if source.platform else None,
                {"type": "IN_DATASET", "target": dataset} if dataset else None,
                {"type": "HAS_LANGUAGE", "target": source.language or record.content.language}
                if (source.language or record.content.language)
                else None,
            ]
            if relation is not None
        ]
    }


def idempotency_key(record: CanonicalRecord, *, dataset: str = "") -> str:
    """Stable key for retry-safe indexing of the same canonical record."""
    material = json.dumps(
        {"source_url": record.source_url, "dataset": dataset},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def index_after_save(
    record: CanonicalRecord,
    *,
    enabled: bool,
    indexer: RecordIndexer | None,
    dataset: str = "",
    failure_log: Path | None = None,
) -> IndexResult:
    """Index a stored canonical record without ever failing collection.

    Call this only after canonical storage has succeeded. Failed attempts can be
    replayed from canonical storage; ``failure_log`` is an optional local JSONL hint,
    not an authoritative queue.
    """
    key = idempotency_key(record, dataset=dataset)
    if not enabled or indexer is None:
        return IndexResult("disabled", record.source_url, key)

    payload = graph_ready_payload(record, dataset=dataset)
    try:
        indexer.index(payload, idempotency_key=key)
        return IndexResult("indexed", record.source_url, key)
    except Exception as exc:  # optional integration must never break collection
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("Optional RAG indexing failed for %s: %s", record.source_url, error)
        if failure_log is not None:
            failure_log.parent.mkdir(parents=True, exist_ok=True)
            with failure_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"record_id": record.source_url, "idempotency_key": key, "error": error}) + "\n")
        return IndexResult("failed", record.source_url, key, error)


def validate_collection_relations(payload: dict[str, Any]) -> None:
    """Guard against collection-side leakage of analysis-owned relation types."""
    found = {
        str(item.get("type", ""))
        for item in payload.get("factual_relations", [])
        if isinstance(item, dict)
    }
    forbidden = found & ANALYSIS_ONLY_RELATIONS
    if forbidden:
        raise ValueError(f"analysis-only relations are not allowed in Collection: {sorted(forbidden)}")
