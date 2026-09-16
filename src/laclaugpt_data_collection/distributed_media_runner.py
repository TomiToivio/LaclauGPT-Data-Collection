"""Download pending media to S3/Allas and refresh distributed handoff state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import Settings
from .distributed_capture import DistributedCaptureSink
from .handoff import routing_metadata
from .media import MediaBackend, MediaDownloader, MediaJob
from .media_runner import load_records
from .storage.remote import S3ObjectStore
from .store import CollectionStore


class S3MediaBackend(MediaBackend):
    """MediaDownloader backend that stores deterministic objects in S3/Allas."""

    def __init__(self, object_store: S3ObjectStore) -> None:
        self.object_store = object_store

    def save(self, key: str, data: bytes, mime_type: str) -> str:
        return self.object_store.put_bytes(f"media/{key}", data, content_type=mime_type)

    def exists(self, key: str) -> bool:
        # MediaDownloader's durable SQLite media_index is the idempotency source.
        # S3 puts use deterministic keys, so retrying a missing index row is safe.
        del key
        return False


def apply_media_results(
    records: list[dict[str, Any]],
    jobs: list[MediaJob],
    results: list[dict[str, Any]],
    *,
    default_collection: str,
) -> list[dict[str, Any]]:
    """Copy completed object refs/checksums into affected canonical records."""
    jobs_by_key = {job.media_key: job for job in jobs}
    record_by_route: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        collection_id, _ = routing_metadata(record, default_collection=default_collection)
        source_url = str(record.get("source_url") or "")
        if source_url:
            record_by_route[(collection_id, source_url)] = record

    touched: dict[tuple[str, str], dict[str, Any]] = {}
    for result in results:
        if result.get("status") != "completed":
            continue
        job = jobs_by_key.get(str(result.get("media_key") or ""))
        if job is None:
            continue
        record = record_by_route.get((job.collection_id, job.source_id))
        if record is None:
            continue
        content = record.setdefault("content", {})
        refs = content.setdefault("media_references", [])
        for position, ref in enumerate(refs):
            if not isinstance(ref, dict):
                continue
            index = int(ref.get("media_index", position))
            if index != job.media_index:
                continue
            if str(ref.get("url") or "") != job.url:
                continue
            ref["object_ref"] = str(result.get("local_path") or "")
            ref["checksum"] = str(result.get("sha256") or "")
            metadata = ref.setdefault("metadata", {})
            metadata["byte_size"] = result.get("byte_size")
            metadata["mime_type"] = result.get("mime_type")
            metadata["download_status"] = "completed"
            touched[(job.collection_id, job.source_id)] = record
            break
    return list(touched.values())


def run_distributed_media(
    settings: Settings,
    *,
    study_config: str | Path,
    data_root: str | Path,
    workers: int = 4,
    limit: int = 100,
) -> dict[str, Any]:
    """Download a bounded media batch, update MongoDB and emit readiness events."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    sink = DistributedCaptureSink(settings)
    sink.assert_private_config(study_config)

    records = load_records(data_root)[:limit]
    store = CollectionStore(data_root)
    try:
        object_store = S3ObjectStore(
            bucket=settings.s3_bucket,
            endpoint_url=settings.effective_s3_endpoint,
            region_name=settings.s3_region,
            access_key_id=settings.effective_s3_access_key,
            secret_access_key=settings.effective_s3_secret_key,
            prefix=f"{settings.s3_prefix_root}/{settings.project_id}",
            signature_version=settings.s3_signature_version,
            addressing_style=settings.s3_addressing_style,
        )
        downloader = MediaDownloader(
            store,
            backend=S3MediaBackend(object_store),
            workers=workers,
        )
        jobs = downloader.enqueue_from_records(records)
        results = downloader.run_queue(jobs)
        touched = apply_media_results(
            records,
            jobs,
            results,
            default_collection=settings.project_id,
        )
        for record in touched:
            sink.ingest(record)
        return {
            "project_id": settings.project_id,
            "run_id": settings.run_id,
            "records_scanned": len(records),
            "queued": len(jobs),
            "completed": sum(row.get("status") == "completed" for row in results),
            "failed": sum(row.get("status") == "failed" for row in results),
            "mongo_refreshed": len(touched),
        }
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="laclaugpt-distributed-media")
    parser.add_argument("--study-config", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    result = run_distributed_media(
        Settings(),
        study_config=args.study_config,
        data_root=args.data_root,
        workers=args.workers,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
