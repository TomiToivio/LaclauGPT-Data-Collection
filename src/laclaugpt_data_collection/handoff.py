"""Stable Collection -> Analysis handoff contract.

The handoff is storage-neutral. Local cron workers can build the same envelope
from JSONL/SQLite that distributed workers read from MongoDB, while Redis may
optionally announce ready keys without carrying the research payload itself.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Iterable

from .realtime import (
    RealtimePolicy,
    analysis_eligibility,
    source_priority,
    source_publication_time,
)

_READY_MEDIA = {"completed", "downloaded", "ok"}


def routing_metadata(record: dict[str, Any], *, default_collection: str = "default") -> tuple[str, str]:
    """Return ``(collection_id, arena)`` from portable record metadata."""
    collection_id = str(record.get("collection_id") or "")
    arena = str(record.get("arena") or "")
    source = record.get("source") or {}
    raw_metadata = source.get("raw_metadata") or {}
    collection_id = collection_id or str(raw_metadata.get("collection_id") or "")
    arena = arena or str(raw_metadata.get("arena") or "")
    provenance = record.get("provenance") or []
    if provenance and isinstance(provenance[-1], dict):
        metadata = provenance[-1].get("metadata") or {}
        collection_id = collection_id or str(metadata.get("collection_id") or "")
        arena = arena or str(metadata.get("arena") or "")
    return collection_id or default_collection, arena


def source_revision(record: dict[str, Any]) -> str:
    """Hash source-derived inputs that should trigger re-analysis when changed."""
    source = record.get("source") or {}
    content = record.get("content") or {}
    raw_capture = record.get("raw_capture") or {}
    payload = {
        "source_url": record.get("source_url"),
        "source_native_ids": record.get("source_native_ids") or {},
        "source": {
            "platform": source.get("platform"),
            "source_type": source.get("source_type"),
            "author": source.get("author"),
            "created_at": source.get("created_at"),
            "language": source.get("language"),
            "country": source.get("country"),
            "parent_source_url": source.get("parent_source_url"),
        },
        "content": {
            "text": content.get("text"),
            "title": content.get("title"),
            "language": content.get("language"),
            "translated_text": content.get("translated_text"),
            "media_references": content.get("media_references") or [],
            "file_references": content.get("file_references") or [],
        },
        "raw_checksum": raw_capture.get("checksum"),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _media_references(record: dict[str, Any]) -> list[dict[str, Any]]:
    content = record.get("content") or {}
    refs = record.get("media_references") or content.get("media_references") or []
    return [ref for ref in refs if isinstance(ref, dict) and ref.get("url")]


def media_ready(
    record: dict[str, Any],
    media_states: Iterable[dict[str, Any]] | None = None,
) -> tuple[bool, str]:
    """Decide whether required source media is durably available for Analysis."""
    refs = _media_references(record)
    if not refs:
        return True, "no_media_required"

    states = list(media_states or [])
    completed_indexes = {
        int(state.get("media_index", -1))
        for state in states
        if str(state.get("status") or "").lower() in _READY_MEDIA
    }
    for position, ref in enumerate(refs):
        if ref.get("local_ref") or ref.get("object_ref") or ref.get("checksum"):
            continue
        media_index = int(ref.get("media_index", position))
        if media_index not in completed_indexes:
            return False, "waiting_media"
    return True, "media_ready"


#: A source date may legitimately run slightly ahead of the clock that read it: a
#: date-only stamp means midnight in the source's timezone, and a feed can publish a
#: scheduled item. Two days covers both without admitting an event page whose *start
#: date* was mistaken for a publication date (#369) - those were one and two months out.
MAX_PUBLICATION_AHEAD = timedelta(days=2)


def capture_time(record: dict[str, Any]) -> datetime | None:
    """When the collector read the record, from provenance or the record itself."""
    from .realtime import parse_source_time

    for entry in record.get("provenance") or []:
        metadata = entry.get("metadata") if isinstance(entry, dict) else None
        if not isinstance(metadata, dict):
            continue
        for key in ("captured_at", "collected_at"):
            parsed = parse_source_time(metadata.get(key))
            if parsed is not None:
                return parsed
    for key in ("collected_at", "captured_at"):
        parsed = parse_source_time(record.get(key))
        if parsed is not None:
            return parsed
    return None


def publication_is_plausible(
    published: datetime | None, captured: datetime | None
) -> bool:
    """A publication time may not be far ahead of its own capture.

    Missing either side is not a defect: unknown stays unknown. This only rejects the
    impossible, because an event page's start date admitted as a publication date is a
    future row that the study window will silently accept.
    """
    if published is None or captured is None:
        return True
    return published <= captured + MAX_PUBLICATION_AHEAD


def build_handoff(
    record: dict[str, Any],
    *,
    project_id: str = "",
    run_id: str = "",
    media_states: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build an idempotent, machine-readable Analysis handoff envelope."""
    source_url = str(record.get("source_url") or "")
    if not source_url:
        raise ValueError("handoff record requires source_url")
    collection_id, arena = routing_metadata(record, default_collection=project_id or "default")
    revision = source_revision(record)
    published = source_publication_time(record)

    status = "ready"
    reason = "source_ready"
    if not publication_is_plausible(published, capture_time(record)):
        # #369: an event listing's start date is not a publication date. Refusing the row
        # is better than admitting a future record the study window will happily analyse.
        status = "excluded"
        reason = "published_after_capture"
    priority = 2
    if collection_id.casefold() == "ai26":
        policy = RealtimePolicy.ai26()
        eligible, eligibility_reason = analysis_eligibility(record, policy)
        priority = source_priority(record, policy)
        if not eligible:
            status = "excluded"
            reason = eligibility_reason

    if status == "ready":
        ready, media_reason = media_ready(record, media_states)
        if not ready:
            status = "waiting_media"
            reason = media_reason
        elif media_reason == "media_ready":
            reason = media_reason

    key_material = f"{collection_id}\n{source_url}\n{revision}"
    handoff_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    return {
        "contract_version": "1.0",
        "handoff_key": handoff_key,
        "revision": revision,
        "status": status,
        "reason": reason,
        "project_id": project_id,
        "collection_id": collection_id,
        "arena": arena,
        "run_id": run_id,
        "source_url": source_url,
        "published_at": published.isoformat() if published else None,
        "source_priority": priority,
    }


def ready_sort_key(handoff: dict[str, Any]) -> tuple[int, float, str]:
    """Portable priority ordering: source tier, newest first, stable source id."""
    published = handoff.get("published_at")
    timestamp = 0.0
    if isinstance(published, str) and published:
        from .realtime import parse_source_time

        parsed = parse_source_time(published)
        timestamp = parsed.timestamp() if parsed else 0.0
    return (
        int(handoff.get("source_priority") or 2),
        -timestamp,
        str(handoff.get("source_url") or ""),
    )
