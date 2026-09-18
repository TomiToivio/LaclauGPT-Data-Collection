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
from .storage.mongodb import MongoRecordStore


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

    store = MongoRecordStore(
        settings.mongodb_uri,
        settings.mongodb_database,
        settings.effective_mongodb_collection,
        settings.project_id,
        connect_timeout_ms=settings.mongodb_connect_timeout_ms,
        graph_max_depth=settings.mongodb_graph_max_depth,
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
        "warnings": warnings,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    """Phase 0 RSS entry point used by `laclaugpt-server-rss` and the cron wrapper.

    Writes flat Phase 0 documents into the collection the Phase 0 analysis core
    reads (issue #85), so a collected item is directly discoverable by
    `laclaugpt/laclaugpt_process.py`. Redis/S3 are not involved on this path.

    Returns non-zero when collection fails, so cron surfaces the fault.
    """
    from .config import Settings
    from .phase0_mongo import write_phase0_records

    parser = argparse.ArgumentParser(description="Phase 0 RSS collection into MongoDB")
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--collection-id", default=None)
    parser.add_argument("--worker-id", default="laclaugpt-server-rss")
    parser.add_argument("--max-feeds", type=int, default=10)
    parser.add_argument("--per-feed-limit", type=int, default=10)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--json", action="store_true", help="print the batch summary as JSON")
    args = parser.parse_args(argv)

    settings = Settings()
    routed_collection = args.collection_id or settings.project_id
    feeds = select_feed_window(
        load_feed_manifest(args.source_manifest),
        max_feeds=args.max_feeds,
    )
    records, warnings = collect_rss_records(
        feeds,
        collection_id=routed_collection,
        worker_id=args.worker_id,
        per_feed_limit=args.per_feed_limit,
    )

    errors: list[str] = []
    written = 0
    try:
        written = write_phase0_records(settings, records[: args.limit])
    except Exception as exc:  # noqa: BLE001 - report, do not traceback under cron
        errors.append(f"phase0 write failed: {str(exc)[:180]}")

    summary = {
        "status": "ok" if not errors else "error",
        "project_id": settings.project_id,
        "collection": f"laclaugpt2_{settings.project_id}_scraper_collection",
        "worker_id": args.worker_id,
        "records_collected": len(records),
        "records_written": written,
        "warnings": warnings,
        "errors": errors,
    }
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(
            f"[phase0] collected={len(records)} written={written} "
            f"errors={len(errors)} collection={summary['collection']}"
        )
        for warning in warnings:
            print(f"  warning: {warning}")
        for error in errors:
            print(f"  error: {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
