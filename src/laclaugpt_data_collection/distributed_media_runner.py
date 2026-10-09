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
from .media import FilesystemBackend, MediaBackend, MediaDownloader, MediaJob
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


def repair_media_references(
    records: list[dict[str, Any]],
    media_states: dict[str, list[dict[str, Any]]],
    *,
    default_collection: str,
) -> list[dict[str, Any]]:
    """Re-attach completed media references the record lost to a later re-ingest.

    Issue #210: re-ingest replaces the whole document, so a ref whose object is
    already durably stored comes back with ``object_ref == ""``. The downloader
    then skips it (the media index says ``completed``, which is terminal), so
    nothing in the scheduled path can ever clear it — 97 records (12.3% of the
    store) were invisible to Analysis for this reason.

    The durable state is not lost: the SQLite ``media_index`` still carries the
    S3 path and checksum. This copies that state back onto any ref the record
    still lists but whose ``object_ref`` is empty, and returns the records it
    changed. It writes nothing itself; the caller re-ingests what it returns.

    A ref is repaired only when its media_index row's status is terminal
    *and* records a non-empty local_path, so a genuinely unfinished download is
    left for the downloader.
    """
    from .media import TERMINAL_MEDIA_STATUSES

    touched: list[dict[str, Any]] = []
    for record in records:
        collection_id, _ = routing_metadata(record, default_collection=default_collection)
        source_id = str(record.get("source_url") or "")
        if not source_id:
            continue
        content = record.get("content")
        if not isinstance(content, dict):
            continue
        refs = content.get("media_references")
        if not isinstance(refs, list) or not refs:
            continue
        states = media_states.get(source_id)
        if not states:
            continue
        by_index: dict[int, dict[str, Any]] = {}
        for state in states:
            status = str(state.get("status") or "")
            path = str(state.get("local_path") or "")
            if status in TERMINAL_MEDIA_STATUSES and path:
                by_index[int(state.get("media_index", -1))] = state
        changed = False
        for position, ref in enumerate(refs):
            if not isinstance(ref, dict):
                continue
            if str(ref.get("object_ref") or ""):
                continue
            state = by_index.get(int(ref.get("media_index", position)))
            if state is None:
                continue
            # Prefer the row whose recorded url matches the ref, so a shifted
            # index cannot attach the wrong object.
            state_url = str(state.get("url") or "")
            ref_url = str(ref.get("url") or "")
            if state_url and ref_url and state_url != ref_url:
                continue
            ref["object_ref"] = str(state.get("local_path") or "")
            ref["checksum"] = str(state.get("sha256") or "")
            metadata = ref.setdefault("metadata", {})
            metadata.setdefault("byte_size", state.get("byte_size"))
            metadata.setdefault("mime_type", state.get("mime_type"))
            metadata["download_status"] = "completed"
            metadata["repaired_from_media_index"] = True
            changed = True
        if changed:
            touched.append(record)
    return touched


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


def _run_local_media_unlocked(
    settings: Settings,
    *,
    study_config: str | Path,
    data_root: str | Path,
    workers: int,
    limit: int,
) -> dict[str, Any]:
    """Use the existing persistent media index without instantiating remote services."""
    if not Path(study_config).is_file():
        raise FileNotFoundError("Private study configuration is required for media collection")
    records = [
        record
        for record in load_records(data_root)
        if routing_metadata(record, default_collection=settings.project_id)[0]
        == settings.project_id
    ][:limit]
    store = CollectionStore(data_root)
    try:
        downloader = MediaDownloader(
            store,
            backend=FilesystemBackend(store.media_dir, store.root),
            workers=workers,
        )
        jobs = downloader.enqueue_from_records(records)
        results = downloader.run_queue(jobs)
        return {
            "project_id": settings.project_id,
            "run_id": settings.run_id,
            "storage": "filesystem",
            "records_scanned": len(records),
            "remote_records": 0,
            "local_records": len(records),
            "queued": len(jobs),
            "attempted": len(results),
            "completed": sum(row.get("status") == "completed" for row in results),
            "failed": sum(row.get("status") == "failed" for row in results),
            "access_restricted": sum(row.get("status") == "access_restricted" for row in results),
            "skipped": max(len(records) - len(jobs), 0),
            "mongo_refreshed": 0,
        }
    finally:
        store.close()


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
        # Issue #210: repair refs whose durable media already exists but whose
        # document lost the back-reference to a later re-ingest. This runs FIRST,
        # before enqueue, because the downloader skips these rows by design (the
        # media index says "completed", which is terminal) and would otherwise
        # never revisit them. Repaired refs also stop the record appearing in the
        # pending set on the next cycle.
        repaired: list[dict[str, Any]] = []
        try:
            repair_states = {
                str(record.get("source_url") or ""): store.media_states(
                    str(record.get("source_url") or ""),
                    collection_id=settings.project_id,
                )
                for record in records
                if record.get("source_url")
            }
            repaired = repair_media_references(
                records,
                repair_states,
                default_collection=settings.project_id,
            )
        except Exception as exc:  # noqa: BLE001
            sink.notification_errors.append(f"media-ref repair skipped: {exc}")

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
        for record in repaired:
            if record not in touched:
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
            "access_restricted": sum(row.get("status") == "access_restricted" for row in results),
            "skipped": max(len(records) - len(jobs), 0),
            "mongo_refreshed": len(touched),
            "media_refs_repaired": len(repaired),
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
    runner = (
        _run_distributed_media_unlocked
        if settings.distributed_requested
        else _run_local_media_unlocked
    )
    if not use_lock:
        return runner(
            settings,
            study_config=study_config,
            data_root=data_root,
            workers=workers,
            limit=limit,
        )
    with media_run_lock(data_root):
        return runner(
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
