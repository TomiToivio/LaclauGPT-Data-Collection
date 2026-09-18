"""Linux-server non-browser collector for the first distributed AI26 test.

The initial server worker deliberately starts with RSS/Atom because feeds are the
highest-value, lowest-friction AI26 source family. It uses the same MongoDB,
Redis and S3/Allas distributed sink as Firefox collection on the laptop.
"""
from __future__ import annotations

import argparse
import json
import time
import tomllib
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .collectors.rss import RSSCollector
from .config import Settings
from .models import CanonicalRecord


def phase0_collection_name(project_id: str) -> str:
    """Return the legacy Phase 0 collection consumed by Data Analysis."""
    return f"laclaugpt2_{project_id}_scraper_collection"


def phase0_document(record: CanonicalRecord) -> dict[str, Any]:
    """Flatten one RSS record to the deliberately minimal Phase 0 Mongo contract."""
    source_name = str(record.source.raw_metadata.get("source_name") or "")
    source_type = record.source.source_type or record.source.platform or "rss"
    actor_name = record.source.author_fullname or record.source.author or source_name
    document_id = record.source_native_ids.get("document_id") or sha256(
        record.source_url.encode("utf-8")
    ).hexdigest()
    return {
        "document_id": str(document_id),
        "source_url": record.source_url,
        "source_text": record.content.text or "",
        "source_title": record.content.title or "",
        "title": record.content.title or "",
        "source_date": record.source.created_at,
        "source_name": source_name,
        "source_type": source_type,
        "actor_name": actor_name,
        "language": record.source.language or record.content.language or "",
        "arena": str(record.source.raw_metadata.get("arena") or ""),
    }


class Phase0MongoStore:
    """RSS-only compatibility store for the hand-coded Phase 0 analysis core."""

    def __init__(
        self,
        uri: str,
        database: str,
        project_id: str,
        *,
        connect_timeout_ms: int = 2000,
        client_factory: Any | None = None,
    ) -> None:
        if client_factory is None:
            try:
                from pymongo import MongoClient
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError(
                    "Install laclaugpt-data-collection[distributed] for MongoDB"
                ) from exc
            client_factory = MongoClient
        self.collection_name = phase0_collection_name(project_id)
        client = client_factory(uri, serverSelectionTimeoutMS=connect_timeout_ms)
        self._collection = client[database][self.collection_name]
        self._collection.create_index(
            [("document_id", 1)], unique=True, name="phase0_document_id_unique"
        )
        self._collection.create_index(
            [("source_url", 1)], unique=True, name="phase0_source_url_unique"
        )

    def upsert(self, record: CanonicalRecord) -> None:
        document = phase0_document(record)
        self._collection.update_one(
            {"document_id": document["document_id"]},
            {"$set": document},
            upsert=True,
        )


def load_feed_manifest(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate the public/private `[[feed]]` source-manifest convention."""
    manifest = Path(path)
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    feeds = data.get("feed") or []
    if not isinstance(feeds, list):
        raise ValueError("source manifest 'feed' must be an array of tables")
    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(feeds, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"source manifest feed #{index} must be a table")
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"source manifest feed #{index} enabled must be boolean")
        if not enabled:
            continue
        name = str(entry.get("name") or "").strip()
        feed_url = str(entry.get("feed_url") or "").strip()
        if not name:
            raise ValueError(f"source manifest feed #{index} requires a name")
        parsed = urlsplit(feed_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                f"source manifest feed {name!r} requires an http(s) feed_url"
            )
        priority = str(entry.get("priority") or "").strip()
        if priority and priority not in {"P1", "P2", "P3"}:
            raise ValueError(
                f"source manifest feed {name!r} priority must be P1, P2 or P3"
            )
        rows.append(dict(entry))
    return rows


def _stamp_source_metadata(
    record: Any,
    feed: dict[str, Any],
    *,
    collection_id: str,
    worker_id: str,
) -> CanonicalRecord:
    record.source.raw_metadata["collection_id"] = collection_id
    record.source.raw_metadata["source_name"] = str(feed.get("name") or "")
    record.source.raw_metadata["source_family"] = str(feed.get("source_family") or "")
    record.source.raw_metadata["sampling_priority"] = str(feed.get("priority") or "")
    arena = str(feed.get("arena") or "")
    if arena:
        record.source.raw_metadata["arena"] = arena
    if record.provenance:
        metadata = record.provenance[-1].metadata
        metadata["collection_id"] = collection_id
        metadata["worker_id"] = worker_id
        metadata["source_name"] = str(feed.get("name") or "")
        if arena:
            metadata["arena"] = arena
    record.refresh_human_readable()
    return record


def collect_rss_records(
    feeds: list[dict[str, Any]],
    *,
    collection_id: str,
    worker_id: str,
    per_feed_limit: int = 20,
) -> tuple[list[CanonicalRecord], list[str]]:
    """Collect and annotate RSS records without touching distributed services."""
    records: list[CanonicalRecord] = []
    warnings: list[str] = []
    for feed in feeds:
        feed_url = str(feed["feed_url"])
        result = RSSCollector([feed_url], max_items_per_feed=per_feed_limit).collect()
        warnings.extend(result.warnings)
        for record in result.records:
            records.append(
                _stamp_source_metadata(
                    record,
                    feed,
                    collection_id=collection_id,
                    worker_id=worker_id,
                )
            )
    return records, warnings


def _priority_rank(feed: dict[str, Any]) -> int:
    """Order feeds by declared sampling priority (unknown defaults to P2)."""
    return {"P1": 1, "P2": 2, "P3": 3}.get(
        str(feed.get("priority") or "").strip().upper(), 2
    )


def select_feed_window(
    feeds: list[dict[str, Any]],
    *,
    max_feeds: int,
    rotation: int = 0,
) -> list[dict[str, Any]]:
    """Pick a bounded feed window without permanently starving the manifest tail.

    A plain ``feeds[:max_feeds]`` slice means the same first rows are polled on
    every tick and everything after them is never collected, which silently
    narrows the study's source mix. Rotating the priority-ordered list by
    ``rotation`` positions guarantees that across successive ticks every
    manifest entry is eventually polled, while high-priority feeds stay at the
    front of each cycle. ``sorted`` is stable, so equal priorities keep their
    manifest order.
    """
    if max_feeds < 1:
        raise ValueError("max_feeds must be at least 1")
    if not feeds:
        return []
    ordered = sorted(feeds, key=_priority_rank)
    shift = rotation % len(ordered)
    rotated = ordered[shift:] + ordered[:shift]
    return rotated[:max_feeds]


def run_distributed_rss(
    settings: Settings,
    *,
    source_manifest: str | Path,
    collection_id: str | None = None,
    worker_id: str = "linux-server-rss",
    max_feeds: int = 10,
    per_feed_limit: int = 10,
    limit: int = 50,
    rotation: int | None = None,
) -> dict[str, Any]:
    """Run one bounded Phase 0 RSS batch and upsert directly to MongoDB."""
    if max_feeds < 1 or per_feed_limit < 1 or limit < 1:
        raise ValueError("max_feeds, per_feed_limit and limit must be at least 1")
    if not settings.mongodb_uri:
        raise RuntimeError("Phase 0 RSS collection requires LACLAUGPT_MONGODB_URI")

    routed_collection = collection_id or settings.project_id
    if rotation is None:
        rotation = int(time.time() // 3600) * max_feeds
    feeds = select_feed_window(
        load_feed_manifest(source_manifest),
        max_feeds=max_feeds,
        rotation=rotation,
    )
    records, warnings = collect_rss_records(
        feeds,
        collection_id=routed_collection,
        worker_id=worker_id,
        per_feed_limit=per_feed_limit,
    )

    store = Phase0MongoStore(
        settings.mongodb_uri,
        settings.mongodb_database,
        settings.project_id,
        connect_timeout_ms=settings.mongodb_connect_timeout_ms,
    )

    synced = 0
    errors: list[str] = []
    for record in records[:limit]:
        try:
            store.upsert(record)
            synced += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{record.source_url}: {str(exc)[:180]}")

    return {
        "status": "ok" if not errors else "partial",
        "project_id": settings.project_id,
        "collection_id": routed_collection,
        "worker_id": worker_id,
        "feeds_considered": len(feeds),
        "feed_names": [str(feed.get("name") or "") for feed in feeds],
        "records_collected": len(records),
        "records_synced": synced,
        "mongodb_collection": store.collection_name,
        "warnings": warnings,
        "errors": errors,
    }
