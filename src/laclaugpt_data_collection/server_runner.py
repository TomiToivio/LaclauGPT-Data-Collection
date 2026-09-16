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
from .distributed_capture import DistributedCaptureSink
from .handoff import build_handoff, ready_sort_key


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
) -> dict[str, Any]:
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
    payload = record.model_dump(mode="json")
    payload["collection_id"] = collection_id
    payload["arena"] = arena
    return payload


def collect_rss_records(
    feeds: list[dict[str, Any]],
    *,
    collection_id: str,
    worker_id: str,
    per_feed_limit: int = 20,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect and annotate RSS records without touching distributed services."""
    records: list[dict[str, Any]] = []
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
    """Run a bounded RSS batch and write eligible records to shared backends."""
    if max_feeds < 1 or per_feed_limit < 1 or limit < 1:
        raise ValueError("max_feeds, per_feed_limit and limit must be at least 1")
    sink = DistributedCaptureSink(settings)
    sink.assert_private_config(source_manifest)
    routed_collection = collection_id or settings.project_id
    if rotation is None:
        # Advance the window once per hour so a hourly cron covers the whole
        # manifest over successive ticks without persisting extra state.
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

    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    excluded = 0
    for record in records:
        handoff = build_handoff(
            record,
            project_id=settings.project_id,
            run_id=settings.run_id,
        )
        if handoff["status"] == "excluded":
            excluded += 1
            continue
        candidates.append((record, handoff))
    candidates.sort(key=lambda pair: ready_sort_key(pair[1]))

    synced = 0
    duplicate_leases = 0
    errors: list[str] = []
    for record, handoff in candidates[:limit]:
        handoff_key = str(handoff["handoff_key"])
        if not sink.redis.acquire_once(
            f"server-rss:{settings.run_id}:{handoff_key}",
            ttl_seconds=30 * 24 * 3600,
        ):
            duplicate_leases += 1
            continue
        try:
            sink.ingest(record)
            synced += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{record.get('source_url', '')}: {str(exc)[:180]}")

    return {
        "status": "ok" if not errors else "partial",
        "project_id": settings.project_id,
        "collection_id": routed_collection,
        "run_id": settings.run_id,
        "worker_id": worker_id,
        "feeds_considered": len(feeds),
        "feed_names": [str(feed.get("name") or "") for feed in feeds],
        "records_collected": len(records),
        "records_excluded": excluded,
        "records_synced": synced,
        "duplicate_leases": duplicate_leases,
        "warnings": warnings,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="laclaugpt-server-rss")
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--collection-id")
    parser.add_argument("--worker-id", default="linux-server-rss")
    parser.add_argument("--max-feeds", type=int, default=10)
    parser.add_argument("--per-feed-limit", type=int, default=10)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--rotation",
        type=int,
        default=None,
        help="feed-window rotation offset; defaults to an hourly advancing offset",
    )
    args = parser.parse_args(argv)
    result = run_distributed_rss(
        Settings(),
        source_manifest=args.source_manifest,
        collection_id=args.collection_id,
        worker_id=args.worker_id,
        max_feeds=args.max_feeds,
        per_feed_limit=args.per_feed_limit,
        limit=args.limit,
        rotation=args.rotation,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
