"""Download pending media to S3/Allas and refresh distributed handoff state."""
from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import Settings
from .distributed_capture import DistributedCaptureSink
from .handoff import routing_metadata
from .media import MediaBackend, MediaDownloader, MediaJob
from .media_runner import load_records
from .storage.remote import S3ObjectStore
from .store import CollectionStore


class MediaRunLockedError(RuntimeError):
    """Raised when another media run already owns the data-root lock."""


@contextmanager
def media_run_lock(data_root: str | Path) -> Iterator[Path]:
    """Hold an atomic per-data-root lock for a media run.

    O_EXCL makes acquisition race-safe for cron invocations on the same host.
    The file contains only the current PID and is removed on normal or exceptional
    exit. A stale lock can be removed manually after verifying no downloader is
    still running.
    """

    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".distributed-media.lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise MediaRunLockedError(f"media run already active: {lock_path}") from exc
    try:
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        os.close(fd)
        yield lock_path
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


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


def _run_distributed_media_unlocked(
    settings: Settings,
    *,
    study_config: str | Path,
    data_root: str | Path,
    workers: int,
    limit: int,
) -> dict[str, Any]:
    sink = DistributedCaptureSink(settings)
    sink.assert_private_config(study_config)

    remote_records = sink.records.pending_media_records(
        collection_id=settings.project_id,
        limit=limit,
    )
    local_records = [
        record
        for record in load_records(data_root)
        if routing_metadata(record, default_collection=settings.project_id)[0] == settings.project_id
    ]

    # MongoDB is authoritative in distributed Phase 1 operation.  Local JSONL is
    # retained as a recovery/debug fallback and can contribute records that have
    # not reached the shared plane yet.  Deduplicate on canonical study identity.
    records_by_route: dict[tuple[str, str], dict[str, Any]] = {}
    for record in local_records:
        collection_id, _ = routing_metadata(record, default_collection=settings.project_id)
        source_url = str(record.get("source_url") or "")
        if source_url:
            records_by_route[(collection_id, source_url)] = record
    for record in remote_records:
        collection_id, _ = routing_metadata(record, default_collection=settings.project_id)
        source_url = str(record.get("source_url") or "")
        if source_url:
            records_by_route[(collection_id, source_url)] = record
    records = list(records_by_route.values())[:limit]
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
            "remote_records": len(remote_records),
            "local_records": len(local_records),
            "queued": len(jobs),
            "attempted": len(results),
            "completed": sum(row.get("status") == "completed" for row in results),
            "failed": sum(row.get("status") == "failed" for row in results),
            "skipped": max(len(records) - len(jobs), 0),
            "mongo_refreshed": len(touched),
        }
    finally:
        store.close()


def run_distributed_media(
    settings: Settings,
    *,
    study_config: str | Path,
    data_root: str | Path,
    workers: int = 4,
    limit: int = 100,
    use_lock: bool = False,
) -> dict[str, Any]:
    """Download a bounded media batch, update MongoDB and emit readiness events."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if not use_lock:
        return _run_distributed_media_unlocked(
            settings,
            study_config=study_config,
            data_root=data_root,
            workers=workers,
            limit=limit,
        )
    with media_run_lock(data_root):
        return _run_distributed_media_unlocked(
            settings,
            study_config=study_config,
            data_root=data_root,
            workers=workers,
            limit=limit,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="laclaugpt-distributed-media")
    parser.add_argument("--study-config", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--lock", action="store_true", help="prevent overlapping cron runs")
    args = parser.parse_args(argv)
    try:
        result = run_distributed_media(
            Settings(),
            study_config=args.study_config,
            data_root=args.data_root,
            workers=args.workers,
            limit=args.limit,
            use_lock=args.lock,
        )
    except MediaRunLockedError as exc:
        print(json.dumps({"status": "locked", "error": str(exc)}, sort_keys=True))
        return 75
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
