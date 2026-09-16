from __future__ import annotations

from laclaugpt_data_collection.media import MediaDownloader
from laclaugpt_data_collection.store import CollectionStore


def record(collection_id: str, url: str = "https://cdn.example/video.mp4") -> dict:
    return {
        "source_url": "https://www.tiktok.com/@research/video/123",
        "source": {"platform": "tiktok"},
        "content": {
            "media_references": [
                {"kind": "video", "url": url, "media_index": 0},
            ]
        },
        "provenance": [{"metadata": {"collection_id": collection_id}}],
    }


def test_success_is_persisted_and_duplicate_cron_run_is_safe(tmp_path):
    store = CollectionStore(tmp_path)
    calls = []

    def fetch(url: str):
        calls.append(url)
        return b"video-bytes", "video/mp4"

    downloader = MediaDownloader(store, workers=1, fetcher=fetch)
    jobs = downloader.enqueue_from_records([record("AI26")])
    result = downloader.run_queue(jobs)

    assert result[0]["status"] == "completed"
    assert result[0]["sha256"]
    assert len(calls) == 1
    assert downloader.enqueue_from_records([record("AI26")]) == []
    assert len(calls) == 1
    store.close()


def test_failed_download_is_retried_on_next_run(tmp_path):
    store = CollectionStore(tmp_path)
    attempts = 0

    def fetch(_url: str):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporary CDN failure")
        return b"recovered", "video/mp4"

    downloader = MediaDownloader(store, workers=1, fetcher=fetch)
    first = downloader.run_queue(downloader.enqueue_from_records([record("AI26")]))
    assert first[0]["status"] == "failed"

    second_jobs = downloader.enqueue_from_records([record("AI26")])
    assert len(second_jobs) == 1
    second = downloader.run_queue(second_jobs)
    assert second[0]["status"] == "completed"
    assert attempts == 2
    store.close()


def test_same_source_can_belong_to_simultaneous_collections(tmp_path):
    store = CollectionStore(tmp_path)
    downloader = MediaDownloader(
        store, workers=1, fetcher=lambda _url: (b"asset", "video/mp4")
    )
    jobs = downloader.enqueue_from_records([record("AI26"), record("Brazil26")])

    assert len(jobs) == 2
    assert jobs[0].media_key != jobs[1].media_key
    assert {job.collection_id for job in jobs} == {"AI26", "Brazil26"}
    results = downloader.run_queue(jobs)
    assert {row["status"] for row in results} == {"completed"}
    store.close()


def test_flat_legacy_record_is_supported(tmp_path):
    store = CollectionStore(tmp_path)
    downloader = MediaDownloader(store, workers=1, fetcher=lambda _url: (b"x", "image/jpeg"))
    legacy = {
        "collection_id": "AI26",
        "platform": "instagram",
        "document_id": "legacy-1",
        "media_references": [
            {"kind": "image", "url": "https://cdn.example/image.jpg", "media_index": 0}
        ],
    }
    jobs = downloader.enqueue_from_records([legacy])
    assert len(jobs) == 1
    assert jobs[0].platform == "instagram"
    assert downloader.run_queue(jobs)[0]["status"] == "completed"
    store.close()
