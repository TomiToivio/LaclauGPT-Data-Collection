"""Bounded Phase 1 AI26 non-browser worker for Laskin.

The worker consumes the shared study/source manifest, never starts browser/X
collection, and writes every collected record through the canonical distributed
MongoDB/Redis/S3 plane. Machine identity is provenance only.
"""
from __future__ import annotations

import argparse
import json
import time
import tomllib
from pathlib import Path
from typing import Any

from .collectors.arxiv import ArxivCollector
from .collectors.bluesky import BlueskyCollector
from .collectors.youtube import YouTubeCollector
from .config import Settings
from .distributed_capture import DistributedCaptureSink
from .models import CollectionProvenance, NormalizedRecord
from .realtime import RealtimePolicy, parse_source_time
from .server_runner import run_phase1_rss
from .web_fetch import fetch_web_child

_BROWSER_ONLY_TABLES = {"x_account", "browser_source", "instagram_account", "tiktok_account"}
_NON_BROWSER_TABLES = (
    "web_source",
    "bluesky_account",
    "mastodon_account",
    "youtube_source",
    "scholarly_query",
)


def load_non_browser_jobs(path: str | Path) -> list[dict[str, Any]]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    jobs: list[dict[str, Any]] = []
    for table in _NON_BROWSER_TABLES:
        rows = data.get(table) or []
        if not isinstance(rows, list):
            raise ValueError(f"source manifest {table!r} must be an array of tables")
        for row in rows:
            if not isinstance(row, dict) or row.get("enabled", row.get("active", True)) is False:
                continue
            jobs.append({"kind": table, **row})
    return jobs


def select_job_window(
    jobs: list[dict[str, Any]], *, max_jobs: int, rotation: int = 0
) -> list[dict[str, Any]]:
    if max_jobs < 1:
        raise ValueError("max_jobs must be at least 1")
    if not jobs:
        return []
    rank = {"P1": 1, "P2": 2, "P3": 3}
    ordered = sorted(jobs, key=lambda row: rank.get(str(row.get("priority", "P2")).upper(), 2))
    shift = rotation % len(ordered)
    return (ordered[shift:] + ordered[:shift])[:max_jobs]


def _stamp(record: NormalizedRecord, row: dict[str, Any], *, collection_id: str, worker_id: str):
    record.source.raw_metadata["collection_id"] = collection_id
    record.source.raw_metadata["source_name"] = str(row.get("name") or "")
    record.source.raw_metadata["source_family"] = str(row.get("source_family") or "")
    record.source.raw_metadata["sampling_priority"] = str(row.get("priority") or "")
    arena = str(row.get("arena") or "")
    if arena:
        record.source.raw_metadata["arena"] = arena
    if record.provenance:
        record.provenance[-1].metadata.update(
            {
                "collection_id": collection_id,
                "worker_id": worker_id,
                "source_name": str(row.get("name") or ""),
            }
        )
        if arena:
            record.provenance[-1].metadata["arena"] = arena
    record.refresh_human_readable()
    return record


def _records_for_job(
    row: dict[str, Any], *, collection_id: str, worker_id: str, per_source_limit: int
) -> tuple[list[NormalizedRecord], list[str]]:
    kind = str(row["kind"])
    warnings: list[str] = []
    if kind == "bluesky_account":
        handle = str(row.get("handle") or "").strip()
        if not handle:
            return [], ["bluesky_account missing handle"]
        result = BlueskyCollector(actor=handle, max_results=per_source_limit).collect()
        return [_stamp(r, row, collection_id=collection_id, worker_id=worker_id) for r in result.records], list(result.warnings)

    if kind == "scholarly_query":
        services = {str(v).lower() for v in row.get("services") or []}
        if "arxiv" not in services:
            return [], [f"{row.get('name','scholarly_query')}: no supported scholarly backend in this tick"]
        query = str(row.get("query") or "").strip()
        if not query:
            return [], ["scholarly_query missing query"]
        result = ArxivCollector(query, max_results=per_source_limit).collect()
        return [_stamp(r, row, collection_id=collection_id, worker_id=worker_id) for r in result.records], list(result.warnings)

    if kind == "youtube_source":
        urls = row.get("video_urls") or ([] if not row.get("video_url") else [row["video_url"]])
        if not urls:
            return [], [f"{row.get('name','youtube_source')}: no video_urls configured; channel discovery remains disabled"]
        result = YouTubeCollector([str(v) for v in urls], page_size=per_source_limit).collect()
        return [_stamp(r, row, collection_id=collection_id, worker_id=worker_id) for r in result.records], list(result.warnings)

    if kind == "web_source":
        url = str(row.get("homepage") or row.get("url") or "").strip()
        if not url:
            return [], ["web_source missing homepage/url"]
        parent = NormalizedRecord(
            document_id=url,
            platform="web",
            source_url=url,
            text="",
            raw_payload={},
            collection_provenance=CollectionProvenance(module="ai26-laskin-web-seed"),
        )
        outcome = fetch_web_child(
            url,
            parent,
            collection_id=collection_id,
            arena=str(row.get("arena") or ""),
        )
        if outcome.record is None:
            return [], [f"{row.get('name','web_source')}: {outcome.error}"]
        return [_stamp(outcome.record, row, collection_id=collection_id, worker_id=worker_id)], []

    if kind == "mastodon_account":
        # The checked-in manifest stores actor acct values, while the current
        # generic Mastodon collector is timeline/hashtag based. Do not silently
        # substitute a public timeline for the named actor.
        return [], [f"{row.get('name','mastodon_account')}: actor collection not supported by current adapter"]

    return [], [f"unsupported non-browser source kind: {kind}"]


def run_phase1_laskin(
    settings: Settings,
    *,
    study_config: str | Path,
    source_manifest: str | Path,
    collection_id: str | None = None,
    worker_id: str = "laskin-cron",
    max_feeds: int = 8,
    max_jobs: int = 6,
    per_source_limit: int = 5,
    limit: int = 40,
    rotation: int | None = None,
) -> dict[str, Any]:
    routed = collection_id or settings.project_id
    if routed != settings.project_id:
        raise ValueError("Laskin must use the configured project_id as collection_id")
    if rotation is None:
        rotation = int(time.time() // 3600)

    rss = run_phase1_rss(
        settings,
        study_config=study_config,
        source_manifest=source_manifest,
        collection_id=routed,
        worker_id=worker_id,
        max_feeds=max_feeds,
        per_feed_limit=per_source_limit,
        limit=limit,
        rotation=rotation * max_feeds,
    )
    remaining = max(limit - int(rss.get("records_synced", 0)), 0)
    sink = DistributedCaptureSink(settings)
    sink.assert_private_config(study_config)
    policy = RealtimePolicy.ai26()
    jobs = select_job_window(load_non_browser_jobs(source_manifest), max_jobs=max_jobs, rotation=rotation * max_jobs)
    synced = 0
    collected = 0
    skipped_before_floor = 0
    warnings = list(rss.get("warnings") or [])
    errors = list(rss.get("errors") or [])

    for row in jobs:
        if synced >= remaining:
            break
        try:
            records, source_warnings = _records_for_job(
                row,
                collection_id=routed,
                worker_id=worker_id,
                per_source_limit=per_source_limit,
            )
            warnings.extend(source_warnings)
            collected += len(records)
            for record in records:
                published = parse_source_time(record.source.created_at)
                if policy.publication_date_floor and published and published < policy.publication_date_floor:
                    skipped_before_floor += 1
                    continue
                if synced >= remaining:
                    break
                payload = record.model_dump(mode="json")
                payload["collection_id"] = routed
                arena = str(record.source.raw_metadata.get("arena") or "")
                if arena:
                    payload["arena"] = arena
                sink.ingest(payload)
                synced += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{row.get('kind')}:{row.get('name','unnamed')}: {str(exc)[:180]}")

    return {
        "status": "ok" if not errors else "partial",
        "project_id": settings.project_id,
        "collection_id": routed,
        "worker_id": worker_id,
        "browser_sources_started": 0,
        "rss_records_synced": int(rss.get("records_synced", 0)),
        "non_browser_jobs_considered": len(jobs),
        "non_browser_records_collected": collected,
        "non_browser_records_synced": synced,
        "records_synced": int(rss.get("records_synced", 0)) + synced,
        "skipped_before_publication_floor": int(rss.get("skipped_before_publication_floor", 0)) + skipped_before_floor,
        "warnings": warnings,
        "errors": errors,
        "notification_errors": list(rss.get("notification_errors") or []) + list(sink.notification_errors),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="laclaugpt-ai26-laskin")
    parser.add_argument("--study-config", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--collection-id", default=None)
    parser.add_argument("--worker-id", default="laskin-cron")
    parser.add_argument("--max-feeds", type=int, default=8)
    parser.add_argument("--max-jobs", type=int, default=6)
    parser.add_argument("--per-source-limit", type=int, default=5)
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args(argv)
    result = run_phase1_laskin(
        Settings(),
        study_config=args.study_config,
        source_manifest=args.source_manifest,
        collection_id=args.collection_id,
        worker_id=args.worker_id,
        max_feeds=args.max_feeds,
        max_jobs=args.max_jobs,
        per_source_limit=args.per_source_limit,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
