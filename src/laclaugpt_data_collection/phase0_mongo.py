"""Phase 0 RSS -> MongoDB compatibility path (issue #85).

Phase 0 collection and Phase 0 analysis must share one deliberately minimal MongoDB
boundary so a collected RSS item is discoverable and processable without Redis,
S3/Allas, browser collection, multimodal processing, or a hidden translation step.

The Phase 1 distributed plane writes nested ``CanonicalRecord`` documents to
``<project>__records`` (via ``MongoRecordStore``). The hand-coded Phase 0 analysis
core instead reads flat documents from ``laclaugpt2_<project>_scraper_collection``
and expects fields such as ``source_url``, ``source_text``, ``source_title``,
``source_date``, ``source_name``, ``source_type`` and ``document_id``.

This module is the explicit Phase 0 adapter between them. It is intentionally
small, flat and hand-readable, and it does not redesign the canonical model. It can
be retired when Phase 1 is reintroduced step by step.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

# The single Phase 0 collection naming convention. Analysis reads this exact name,
# so it is defined once here and asserted by the integration test.
PHASE0_COLLECTION_TEMPLATE = "laclaugpt2_{project}_scraper_collection"

# Tracking parameters stripped before hashing so a re-collected article keeps one
# stable identity instead of creating a duplicate per campaign URL.
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref_src", "s"}


def phase0_collection_name(project_id: str) -> str:
    """Return the MongoDB collection the Phase 0 analysis core reads."""
    project = (project_id or "").strip()
    if not project:
        raise ValueError("project_id is required to derive the Phase 0 collection")
    return PHASE0_COLLECTION_TEMPLATE.format(project=project)


def canonicalize_url(url: str) -> str:
    """Strip fragments and tracking parameters so article identity is stable."""
    value = (url or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    kept = [
        (key, item)
        for key, item in _query_pairs(parts.query)
        if key.lower() not in _TRACKING_KEYS
        and not any(key.lower().startswith(prefix) for prefix in _TRACKING_PREFIXES)
    ]
    query = "&".join(f"{key}={item}" if item else key for key, item in kept)
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", query, "")
    )


def _query_pairs(query: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for chunk in query.split("&"):
        if not chunk:
            continue
        key, _, value = chunk.partition("=")
        pairs.append((key, value))
    return pairs


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Phase0Document:
    """The flat document shape the Phase 0 analysis core consumes."""

    document_id: str
    source_url: str
    source_text: str
    source_title: str
    source_date: str
    source_name: str
    source_type: str
    source_feed_url: str
    source_author: str
    source_categories: list[str]
    content_hash: str
    project: str
    arena: str
    actor_name: str
    actor_type: str
    ai_formation: str
    political_formation: str
    country: str
    language: str
    site_name: str
    collected_at: str
    identity_key: str

    def to_document(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_url": self.source_url,
            "source_text": self.source_text,
            "source_title": self.source_title,
            "source_date": self.source_date,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "source_feed_url": self.source_feed_url,
            "source_author": self.source_author,
            "source_categories": list(self.source_categories),
            "content_hash": self.content_hash,
            "project": self.project,
            "arena": self.arena,
            "actor_name": self.actor_name,
            "actor_type": self.actor_type,
            "ai_formation": self.ai_formation,
            "political_formation": self.political_formation,
            "country": self.country,
            "language": self.language,
            "site_name": self.site_name,
            "collected_at": self.collected_at,
        }


def flatten_record(record: Any, *, project_id: str) -> Phase0Document:
    """Flatten a collected record into the Phase 0 analysis field contract.

    Accepts either a canonical nested record (``source.url`` / ``content.text``)
    or an already-flat mapping, so the adapter stays usable from both the RSS
    collector and a test double.
    """
    flat = _flatten(record)
    source_url = canonicalize_url(str(flat.get("source_url") or ""))
    if not source_url:
        raise ValueError("Phase 0 records require a canonical source_url identity")

    text = str(flat.get("source_text") or flat.get("text") or "").strip()
    if not text:
        raise ValueError(f"Phase 0 record {source_url} has no text content")

    identity_key = source_url
    return Phase0Document(
        document_id=str(flat.get("document_id") or "") or _digest(source_url),
        source_url=source_url,
        source_text=text,
        source_title=str(flat.get("source_title") or flat.get("title") or ""),
        source_date=str(flat.get("source_date") or ""),
        source_name=str(flat.get("source_name") or ""),
        source_type=str(flat.get("source_type") or "rss"),
        source_feed_url=str(flat.get("source_feed_url") or flat.get("feed_url") or ""),
        source_author=str(flat.get("source_author") or ""),
        source_categories=[str(item) for item in (flat.get("source_categories") or [])],
        content_hash=str(flat.get("content_hash") or "") or _digest(text),
        project=str(flat.get("project") or project_id),
        arena=str(flat.get("arena") or ""),
        actor_name=str(flat.get("actor_name") or ""),
        actor_type=str(flat.get("actor_type") or ""),
        ai_formation=str(flat.get("ai_formation") or "unknown"),
        political_formation=str(flat.get("political_formation") or "unknown"),
        country=str(flat.get("country") or ""),
        language=str(flat.get("language") or ""),
        site_name=str(flat.get("site_name") or ""),
        collected_at=str(flat.get("collected_at") or datetime.now(timezone.utc).isoformat()),
        identity_key=identity_key,
    )


def _flatten(record: Any) -> dict[str, Any]:
    """Flatten one canonical/normalized record without inventing values."""
    def as_mapping(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        dumped = getattr(value, "model_dump", None)
        if callable(dumped):
            return dict(dumped())
        return {}

    top = as_mapping(record)
    if not top:
        return {}

    source = as_mapping(top.get("source"))
    content = as_mapping(top.get("content"))
    raw = as_mapping(top.get("raw_capture"))

    raw_metadata = as_mapping(source.get("raw_metadata"))
    flat: dict[str, Any] = dict(raw_metadata)

    flat["source_url"] = (
        top.get("source_url") or source.get("url") or raw_metadata.get("source_url") or ""
    )
    flat["source_text"] = (
        content.get("text") or top.get("text") or raw.get("payload") or top.get("source_text") or ""
    )
    flat["source_title"] = content.get("title") or top.get("title") or ""
    flat["source_date"] = source.get("created_at") or top.get("source_date") or ""
    flat["source_name"] = (
        raw_metadata.get("source_name")
        or source.get("name")
        or top.get("source_name")
        or ""
    )
    flat["source_type"] = top.get("source_type") or source.get("source_type") or "rss"
    flat["source_feed_url"] = (
        raw_metadata.get("feed_url") or source.get("feed_url") or top.get("source_feed_url") or ""
    )
    flat["source_author"] = source.get("author") or top.get("source_author") or ""
    flat["source_categories"] = content.get("categories") or top.get("source_categories") or []
    flat["content_hash"] = top.get("content_hash") or ""
    flat["project"] = top.get("project") or raw_metadata.get("project") or ""
    flat["arena"] = raw_metadata.get("arena") or top.get("arena") or ""
    flat["actor_name"] = top.get("actor_name") or raw_metadata.get("actor_name") or ""
    flat["actor_type"] = top.get("actor_type") or raw_metadata.get("actor_type") or ""
    flat["ai_formation"] = top.get("ai_formation") or raw_metadata.get("ai_formation") or "unknown"
    flat["political_formation"] = (
        top.get("political_formation") or raw_metadata.get("political_formation") or "unknown"
    )
    flat["country"] = top.get("country") or raw_metadata.get("country") or ""
    flat["language"] = content.get("language") or source.get("language") or top.get("language") or ""
    site_name = raw_metadata.get("source_name") or source.get("platform") or ""
    flat["site_name"] = str(site_name or "")
    flat["document_id"] = top.get("document_id") or source.get("document_id") or ""
    return flat


def upsert_phase0_documents(
    collection: Any,
    documents: Iterable[Phase0Document],
) -> int:
    """Upsert flat Phase 0 documents keyed on canonical ``source_url``.

    Keying on the canonical URL is what makes a re-run idempotent: collecting the
    same article again updates the existing document instead of appending a copy
    that the analysis core would analyse twice.
    """
    written = 0
    for document in documents:
        collection.update_one(
            {"source_url": document.source_url},
            {"$set": document.to_document()},
            upsert=True,
        )
        written += 1
    return written


def write_phase0_records(
    settings: Any,
    records: Iterable[Any],
    *,
    collection: Any | None = None,
) -> int:
    """Flatten and upsert collected records into the Phase 0 analysis collection."""
    documents = [flatten_record(record, project_id=settings.project_id) for record in records]
    if collection is None:
        from pymongo import MongoClient

        client = MongoClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=getattr(settings, "mongodb_connect_timeout_ms", 2000),
        )
        collection = client[settings.mongodb_database][
            phase0_collection_name(settings.project_id)
        ]
    return upsert_phase0_documents(collection, documents)
