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
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .collectors.rss import RSSCollector
from .config import Settings
from .models import CanonicalRecord


class Phase0MongoStore:
    """Minimal MongoDB adapter for the legacy Phase 0 analysis contract."""

    def __init__(
        self,
        uri: str,
        database: str,
        project_id: str,
        *,
        connect_timeout_ms: int = 2000,
        client_factory: Any | None = None,
    ) -> None:
        if not uri:
            raise RuntimeError("MongoDB URI is required")
        if client_factory is None:
            try:
                from pymongo import MongoClient

                client_factory = MongoClient
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError(
                    "Install laclaugpt-data-collection[distributed] for MongoDB"
                ) from exc
        self.collection_name = f"laclaugpt2_{project_id}_scraper_collection"
        client = client_factory(uri, serverSelectionTimeoutMS=connect_timeout_ms)
        self._collection = client[database][self.collection_name]
        self._collection.create_index("source_url", unique=True, name="source_url_unique")
        self._collection.create_index("document_id", name="document_id")
        self._collection.create_index("source_date", name="source_date")

    def upsert(self, record: CanonicalRecord) -> None:
        metadata = record.source.raw_metadata
        source_title = str(metadata.get("source_title") or record.content.title or "").strip()
        source_name = str(metadata.get("source_name") or "").strip()
        actor_name = str(metadata.get("actor_name") or record.source.author or source_name).strip()
        document_id = str(record.source_native_ids.get("document_id") or record.source_url)
        fields = {
            "document_id": document_id,
            "source_url": record.source_url,
            "source_text": record.content.text,
            "source_title": source_title,
            "source_date": record.source.created_at,
            "source_name": source_name,
            "source_type": record.source.source_type or record.source.platform or "rss",
            "actor_name": actor_name,
            "arena": str(metadata.get("arena") or ""),
            "project": str(metadata.get("collection_id") or ""),
        }
        # Identity is the stable document id when one is known, so a re-collected
        # article updates in place; source_url remains the canonical identity anchor.
        self._collection.update_one(
            {"document_id": document_id},
            {"$set": fields},
            upsert=True,
        )


def phase0_collection_name(project_id: str) -> str:
    """Return the MongoDB collection the Phase 0 analysis core reads.

    Defined in one place (``phase0_mongo``) so collection and analysis cannot drift
    apart; re-exported here because this module is the Phase 0 collection entry
    point and callers import the contract from it.
    """
    from .phase0_mongo import phase0_collection_name as _name

    return _name(project_id)


def phase0_document(record: Any, *, project_id: str = "") -> dict[str, Any]:
    """Return the flat Phase 0 document for a collected record.

    The Phase 0 analysis core reads flat fields (``source_text``, ``source_title``,
    ``source_date``, ``source_name``, ``source_type``, ``actor_name``, ``arena``,
    ``language``) rather than the nested canonical record, so this is the projection
    across that boundary. The field set is deliberately small and explicit: it is the
    contract Phase 0 analysis reads, not a copy of the canonical model.
    """
    def as_mapping(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        dumped = getattr(value, "model_dump", None)
        return dict(dumped()) if callable(dumped) else {}

    top = as_mapping(record)
    source = as_mapping(top.get("source"))
    content = as_mapping(top.get("content"))
    metadata = as_mapping(source.get("raw_metadata"))

    document_id = str(top.get("document_id") or "")
    if not document_id:
        native = as_mapping(top.get("source_native_ids"))
        document_id = str(native.get("document_id") or "") or str(top.get("source_url") or "")
    source_url = str(top.get("source_url") or source.get("url") or "")
    title = str(content.get("title") or top.get("title") or "")
    actor_name = str(
        top.get("actor_name") or metadata.get("actor_name") or source.get("author") or ""
    )

    return {
        "document_id": document_id,
        "source_url": source_url,
        "source_text": str(content.get("text") or top.get("text") or ""),
        "source_title": title,
        "title": title,
        "source_date": str(source.get("created_at") or top.get("source_date") or ""),
        "source_name": str(metadata.get("source_name") or top.get("source_name") or ""),
        "source_type": str(top.get("source_type") or source.get("source_type") or "rss"),
        "actor_name": actor_name,
        "language": str(content.get("language") or source.get("language") or ""),
        "arena": str(metadata.get("arena") or top.get("arena") or ""),
    }


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
    record.source.raw_metadata["actor_name"] = str(feed.get("actor_name") or "")
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


def run_phase1_rss(
    settings: Settings,
    *,
    study_config: str | Path,
    source_manifest: str | Path,
    collection_id: str | None = None,
    worker_id: str = "linux-server-rss",
    max_feeds: int = 10,
    per_feed_limit: int = 10,
    limit: int = 50,
    rotation: int | None = None,
) -> dict[str, Any]:
    """Run one bounded Phase 1 RSS batch through the canonical distributed sink."""
    from .distributed_capture import DistributedCaptureSink
    from .realtime import RealtimePolicy, parse_source_time

    if max_feeds < 1 or per_feed_limit < 1 or limit < 1:
        raise ValueError("max_feeds, per_feed_limit and limit must be at least 1")

    routed_collection = collection_id or settings.project_id
    if routed_collection != settings.project_id:
        raise ValueError(
            "Phase 1 Laskin worker must use the configured project_id as collection_id"
        )
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

    sink = DistributedCaptureSink(settings)
    sink.assert_private_config(study_config)
    policy = RealtimePolicy.ai26()
    synced = 0
    skipped_before_floor = 0
    errors: list[str] = []

    for record in records:
        published = parse_source_time(record.source.created_at)
        if policy.publication_date_floor and published and published < policy.publication_date_floor:
            skipped_before_floor += 1
            continue
        if synced >= limit:
            break
        payload = record.model_dump(mode="json")
        payload["collection_id"] = routed_collection
        arena = str(record.source.raw_metadata.get("arena") or "")
        if arena:
            payload["arena"] = arena
        try:
            sink.ingest(payload)
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
        "skipped_before_publication_floor": skipped_before_floor,
        "mongodb_collection": settings.distributed_namespace.mongo_collection("records"),
        "warnings": warnings,
        "errors": errors,
        "notification_errors": list(sink.notification_errors),
    }


def main(argv: list[str] | None = None) -> int:
    """Phase 1 canonical RSS entry point used by `laclaugpt-server-rss`.

    Writes nested CanonicalRecord documents through the distributed sink. Legacy Phase 0
    helpers remain available in this module for compatibility and rollback work;
    they are not used by the Laskin Phase 1 cron path.

    Returns non-zero when collection fails, so cron surfaces the fault.
    """
    from .config import Settings

    parser = argparse.ArgumentParser(description="Phase 1 RSS collection into canonical storage")
    parser.add_argument("--study-config", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--collection-id", default=None)
    parser.add_argument("--worker-id", default="laclaugpt-server-rss")
    parser.add_argument("--max-feeds", type=int, default=10)
    parser.add_argument("--per-feed-limit", type=int, default=10)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--json", action="store_true", help="print the batch summary as JSON")
    args = parser.parse_args(argv)

    settings = Settings()
    try:
        summary = run_phase1_rss(
            settings,
            study_config=args.study_config,
            source_manifest=args.source_manifest,
            collection_id=args.collection_id,
            worker_id=args.worker_id,
            max_feeds=args.max_feeds,
            per_feed_limit=args.per_feed_limit,
            limit=args.limit,
        )
    except Exception as exc:  # noqa: BLE001 - report, do not traceback under cron
        print(f"[phase1] collection failed: {str(exc)[:200]}")
        return 1

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(
            f"[phase1] collected={summary['records_collected']} "
            f"synced={summary['records_synced']} "
            f"errors={len(summary['errors'])} "
            f"collection={summary.get('mongodb_collection', '')}"
        )
        for warning in summary["warnings"]:
            print(f"  warning: {warning}")
        for error in summary["errors"]:
            print(f"  error: {error}")
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
