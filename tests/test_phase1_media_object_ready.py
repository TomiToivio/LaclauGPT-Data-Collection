"""Phase 1 media waiting -> ready object-storage slice for issue #106."""
from __future__ import annotations

import hashlib

from laclaugpt_data_collection.distributed_media_runner import apply_media_results
from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.media import MediaBackend, MediaDownloader
from laclaugpt_data_collection.models import CanonicalRecord, CollectionProvenance
from laclaugpt_data_collection.store import CollectionStore


class FakeObjectStorage(MediaBackend):
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}

    def save(self, key: str, data: bytes, mime_type: str) -> str:
        assert mime_type == "image/png"
        self.saved[key] = data
        return f"s3://synthetic-bucket/{key}"

    def exists(self, key: str) -> bool:
        return key in self.saved


def _record() -> CanonicalRecord:
    return CanonicalRecord(
        source_url="https://www.tiktok.com/@synthetic/video/106",
        source_native_ids={"document_id": "106"},
        source={
            "platform": "tiktok",
            "source_type": "browser",
            "created_at": "2026-09-20T08:00:00Z",
            "raw_metadata": {},
        },
        content={
            "text": "Synthetic browser-derived record with one media reference.",
            "media_references": [
                {
                    "kind": "image",
                    "url": "https://media.example.invalid/issue-106.png",
                    "media_index": 0,
                }
            ],
        },
        provenance=[
            CollectionProvenance(
                run_id="issue-106",
                method="browser-capture",
                module="browser/firefox",
                metadata={"collection_id": "synthetic"},
            )
        ],
    )


def test_browser_media_moves_waiting_to_ready_once_with_durable_object_identity(tmp_path) -> None:
    record = _record()
    payload = record.model_dump(mode="json")
    waiting = build_handoff(payload, project_id="synthetic")
    assert (waiting["status"], waiting["reason"]) == ("waiting_media", "waiting_media")

    store = CollectionStore(tmp_path)
    backend = FakeObjectStorage()
    calls = 0
    body = b"synthetic-image-bytes"

    def flaky_fetcher(url: str) -> tuple[bytes, str]:
        nonlocal calls
        assert url == "https://media.example.invalid/issue-106.png"
        calls += 1
        if calls == 1:
            raise OSError("synthetic transient fetch failure")
        return body, "image/png"

    downloader = MediaDownloader(store, backend=backend, workers=1, fetcher=flaky_fetcher)

    first_jobs = downloader.enqueue_from_records([payload])
    assert len(first_jobs) == 1
    deterministic_media_key = first_jobs[0].media_key
    first_results = downloader.run_queue(first_jobs)
    assert first_results[0]["status"] == "failed"
    assert calls == 1
    assert build_handoff(payload, project_id="synthetic")["status"] == "waiting_media"

    second_jobs = downloader.enqueue_from_records([payload])
    assert len(second_jobs) == 1
    assert second_jobs[0].media_key == deterministic_media_key
    second_results = downloader.run_queue(second_jobs)
    assert second_results[0]["status"] == "completed"
    assert calls == 2
    assert second_results[0]["sha256"] == hashlib.sha256(body).hexdigest()

    touched = apply_media_results(
        [payload],
        second_jobs,
        second_results,
        default_collection="synthetic",
    )
    assert len(touched) == 1
    ref = payload["content"]["media_references"][0]
    assert ref["object_ref"].startswith("s3://synthetic-bucket/")
    assert ref["checksum"] == hashlib.sha256(body).hexdigest()
    assert ref["metadata"]["download_status"] == "completed"

    ready = build_handoff(payload, project_id="synthetic")
    assert (ready["status"], ready["reason"]) == ("ready", "media_ready")

    # A completed deterministic media key is not queued or transitioned again.
    third_jobs = downloader.enqueue_from_records([payload])
    assert third_jobs == []
    assert apply_media_results([payload], third_jobs, [], default_collection="synthetic") == []

    # Collection transfers source media only. It does not fabricate derived analysis.
    assert payload["intermediate"]["asr"] == []
    assert payload["intermediate"]["ocr"] == []
    assert payload["intermediate"]["frame_analysis"] == []
    assert payload["analysis"] == {}
    store.close()
