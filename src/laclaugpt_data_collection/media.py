"""Source-agnostic multimodal media downloader.

Browser and non-browser collectors can hand canonical records to this module.
Download state is persisted through :class:`CollectionStore`, so short cron
runs are idempotent and failed assets can be retried without blocking others.
The local filesystem is the default backend; object storage can implement the
same small backend interface.
"""
from __future__ import annotations

import hashlib
import mimetypes
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .store import CollectionStore

USER_AGENT = "Mozilla/5.0 (LaclauGPT collector; research)"
TERMINAL_MEDIA_STATUSES = {"completed", "ok", "downloaded", "access_restricted"}


class MediaBackend:
    """Storage interface for local files, S3/Allas or another object store."""

    def save(self, key: str, data: bytes, mime_type: str) -> str:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError


class FilesystemBackend(MediaBackend):
    def __init__(self, root: str | Path, reference_root: str | Path | None = None) -> None:
        self.root = Path(root)
        self.reference_root = Path(reference_root) if reference_root else self.root.parent
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes, mime_type: str) -> str:
        del mime_type
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(data)
        temporary.replace(path)
        try:
            return path.relative_to(self.reference_root).as_posix()
        except ValueError:
            return str(path)

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()


@dataclass(frozen=True)
class MediaJob:
    media_key: str
    collection_id: str
    platform: str
    source_id: str
    media_index: int
    kind: str
    url: str


class MediaDownloader:
    """Persistent queue worker with checksums, retries and collection isolation."""

    def __init__(
        self,
        store: CollectionStore,
        backend: MediaBackend | None = None,
        workers: int = 4,
        fetcher: Callable[[str], tuple[bytes, str]] | None = None,
    ) -> None:
        self.store = store
        self.backend = backend or FilesystemBackend(store.media_dir, store.root)
        self.workers = max(1, workers)
        self._fetcher = fetcher

    @staticmethod
    def _record_fields(record: dict) -> tuple[str, str, str, list[dict]]:
        source = record.get("source") or {}
        content = record.get("content") or {}
        native = record.get("source_native_ids") or {}
        provenance = record.get("provenance") or []
        platform = str(record.get("platform") or source.get("platform") or "source")
        source_id = str(
            record.get("source_url")
            or record.get("document_id")
            or native.get("document_id")
            or ""
        )
        if not source_id:
            raise ValueError("media record requires source_url or source-native identifier")
        collection_id = str(record.get("collection_id") or record.get("study") or "")
        if not collection_id and provenance and isinstance(provenance[-1], dict):
            latest = provenance[-1]
            metadata = latest.get("metadata") or {}
            collection_id = str(
                metadata.get("collection_id")
                or metadata.get("study")
                or latest.get("collection_id")
                or latest.get("study")
                or ""
            )
        collection_id = collection_id or "default"
        refs = record.get("media_references") or content.get("media_references") or []
        return collection_id, platform, source_id, list(refs)

    def enqueue_from_records(self, records: Iterable[dict]) -> list[MediaJob]:
        jobs: list[MediaJob] = []
        queued: set[str] = set()
        for record in records:
            collection_id, platform, source_id, refs = self._record_fields(record)
            source_hash = hashlib.sha256(source_id.encode()).hexdigest()[:16]
            for position, ref in enumerate(refs):
                url = str(ref.get("url") or "")
                if not url:
                    continue
                media_index = int(ref.get("media_index", position))
                media_key = f"{collection_id}:{platform}:{source_hash}:{media_index}"
                if media_key in queued:
                    continue
                known = self.store.media_known(media_key)
                if known and known.get("status") in TERMINAL_MEDIA_STATUSES:
                    continue
                queued.add(media_key)
                jobs.append(MediaJob(
                    media_key=media_key,
                    collection_id=collection_id,
                    platform=platform,
                    source_id=source_id,
                    media_index=media_index,
                    kind=str(ref.get("kind") or "unknown"),
                    url=url,
                ))
        return jobs

    def run_queue(self, jobs: list[MediaJob]) -> list[dict]:
        results: list[dict] = []
        lock = threading.Lock()

        def work(job: MediaJob) -> None:
            outcome = self._download_one(job)
            with lock:
                results.append(outcome)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            list(pool.map(work, jobs))
        return results

    def _download_one(self, job: MediaJob) -> dict:
        # A capture-time handoff may have completed while the cron worker was
        # waiting to run. Never replace terminal state with running.
        known = self.store.media_known(job.media_key)
        if known and known.get("status") in TERMINAL_MEDIA_STATUSES:
            return {
                "media_key": job.media_key,
                "collection_id": job.collection_id,
                "status": "skipped",
            }
        # Persist queued/running state before network I/O. The collection id is
        # part of media_key, so simultaneous AI26/Brazil26 jobs never collide.
        self.store.record_media(
            job.media_key, job.platform, job.source_id, job.media_index, job.url,
            None, None, None, "", "running", None, None,
        )
        try:
            body, mime = self._fetch(job.url)
        except Exception as exc:  # noqa: BLE001
            status = exc.code if isinstance(exc, HTTPError) else None
            session_bound = (
                job.platform == "tiktok"
                and status in {401, 403}
                and (
                    (urlparse(job.url).hostname or "") == "tiktok.com"
                    or (urlparse(job.url).hostname or "").endswith(".tiktok.com")
                )
            )
            outcome_status = "access_restricted" if session_bound else "failed"
            reason = (
                f"HTTP {status}: access restricted" if session_bound
                else f"HTTP {status}" if status is not None
                else type(exc).__name__
            )
            self.store.record_media(
                job.media_key, job.platform, job.source_id, job.media_index, job.url,
                None, None, None, "", outcome_status, reason, status,
            )
            return {"media_key": job.media_key, "collection_id": job.collection_id,
                    "status": outcome_status, "error": reason,
                    "http_status": status}

        mime = (mime or "application/octet-stream").split(";", 1)[0].strip()
        checksum = hashlib.sha256(body).hexdigest()
        extension = (mimetypes.guess_extension(mime) or "").replace(".jpe", ".jpg")
        collection_dir = hashlib.sha256(job.collection_id.encode()).hexdigest()[:10]
        filename = f"{collection_dir}/{job.platform}/{job.media_key.replace(':', '_')}{extension}"
        path = self.backend.save(filename, body, mime)
        self.store.record_media(
            job.media_key, job.platform, job.source_id, job.media_index, job.url,
            path, checksum, len(body), mime, "completed", None, 200,
        )
        return {
            "media_key": job.media_key,
            "collection_id": job.collection_id,
            "status": "completed",
            "local_path": path,
            "sha256": checksum,
            "byte_size": len(body),
            "mime_type": mime,
            "http_status": 200,
        }

    def _fetch(self, url: str) -> tuple[bytes, str]:
        if self._fetcher is not None:
            return self._fetcher(url)
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=120) as response:
            return response.read(), response.headers.get("Content-Type", "application/octet-stream")


class CaptureTimeMediaHandoff:
    """Persist browser-authorized response bytes and reconcile canonical linkage."""

    def __init__(self, store: CollectionStore, backend: MediaBackend | None = None) -> None:
        self.store = store
        self.backend = backend or FilesystemBackend(store.media_dir, store.root)

    @staticmethod
    def _jobs(record: dict) -> list[MediaJob]:
        collection_id, platform, source_id, refs = MediaDownloader._record_fields(record)
        source_hash = hashlib.sha256(source_id.encode()).hexdigest()[:16]
        jobs: list[MediaJob] = []
        for position, ref in enumerate(refs):
            url = str(ref.get("url") or "")
            if not url:
                continue
            media_index = int(ref.get("media_index", position))
            jobs.append(MediaJob(
                media_key=f"{collection_id}:{platform}:{source_hash}:{media_index}",
                collection_id=collection_id,
                platform=platform,
                source_id=source_id,
                media_index=media_index,
                kind=str(ref.get("kind") or "unknown"),
                url=url,
            ))
        return jobs

    def register_record(self, record: dict) -> int:
        """Register references and reconcile bytes captured before canonical JSON."""
        reconciled = 0
        for job in self._jobs(record):
            self.store.register_media_reference(
                job.url, job.media_key, job.platform, job.source_id, job.media_index
            )
            captured = self.store.captured_media(job.url)
            if captured is not None:
                self._complete(job, captured)
                reconciled += 1
        return reconciled

    def capture(self, url: str, body: bytes, mime_type: str) -> dict:
        """Store a bounded browser response once and link every known reference."""
        mime = (mime_type or "application/octet-stream").split(";", 1)[0].strip()
        checksum = hashlib.sha256(body).hexdigest()
        extension = (mimetypes.guess_extension(mime) or ".bin").replace(".jpe", ".jpg")
        path = self.backend.save(f"captured/{checksum}{extension}", body, mime)
        self.store.record_captured_media(url, path, checksum, len(body), mime)
        captured = self.store.captured_media(url)
        assert captured is not None
        references = self.store.media_references_for_url(url)
        for ref in references:
            self._complete(
                MediaJob(
                    media_key=ref["media_key"],
                    collection_id=ref["media_key"].split(":", 1)[0],
                    platform=ref["platform"],
                    source_id=ref["document_id"],
                    media_index=ref["media_index"],
                    kind="unknown",
                    url=url,
                ),
                captured,
            )
        return {
            "status": "completed" if references else "pending_link",
            "local_path": path,
            "sha256": checksum,
            "byte_size": len(body),
            "mime_type": mime,
            "linked": len(references),
        }

    def _complete(self, job: MediaJob, captured: dict) -> None:
        self.store.record_media(
            job.media_key,
            job.platform,
            job.source_id,
            job.media_index,
            job.url,
            captured["local_path"],
            captured["sha256"],
            captured["byte_size"],
            captured["mime_type"],
            "completed",
            None,
            200,
        )
