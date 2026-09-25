"""Issue #188: synthetic access-control and cron idempotency regressions."""
from __future__ import annotations

from urllib.error import HTTPError

from laclaugpt_data_collection.media import MediaDownloader
from laclaugpt_data_collection.store import CollectionStore


def _record(platform: str) -> dict:
    media_host = (
        "v16-webapp-prime.tiktok.com"
        if platform == "tiktok"
        else "cdn.example.invalid"
    )
    return {
        "collection_id": "brazil26",
        "source_url": f"https://{platform}.example.invalid/public/1",
        "source": {"platform": platform},
        "content": {"media_references": [
            {"kind": "video", "media_index": 0,
             "url": f"https://{media_host}/{platform}.mp4?signature=SENSITIVE"}
        ]},
    }


def test_tiktok_session_bound_403_is_terminal_and_redacted(tmp_path):
    store = CollectionStore(tmp_path)
    calls = []

    def denied(url):
        calls.append(url)
        raise HTTPError(url, 403, "SENSITIVE", None, None)

    downloader = MediaDownloader(store, fetcher=denied)
    job = downloader.enqueue_from_records([_record("tiktok")])[0]
    result = downloader.run_queue([job])[0]

    assert result["status"] == "access_restricted"
    assert result["http_status"] == 403
    assert "SENSITIVE" not in str(result)
    states = store.media_states(job.source_id, collection_id="brazil26")
    assert states[0]["status"] == "access_restricted"
    assert downloader.enqueue_from_records([_record("tiktok")]) == []
    assert downloader.run_queue([job])[0]["status"] == "skipped"
    assert len(calls) == 1
    store.close()


def test_other_platform_http_error_remains_retryable(tmp_path):
    store = CollectionStore(tmp_path)
    attempts = 0

    def fetch(url):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError(url, 403, "SENSITIVE", None, None)
        return b"media bytes", "video/mp4"

    downloader = MediaDownloader(store, fetcher=fetch)
    record = _record("instagram")
    first = downloader.run_queue(downloader.enqueue_from_records([record]))
    assert first[0]["status"] == "failed"
    assert "SENSITIVE" not in str(first)
    second = downloader.run_queue(downloader.enqueue_from_records([record]))
    assert second[0]["status"] == "completed"
    assert attempts == 2
    store.close()


def test_completed_media_is_not_overwritten_by_stale_job(tmp_path):
    store = CollectionStore(tmp_path)
    downloader = MediaDownloader(
        store, fetcher=lambda _url: (b"payload", "video/mp4")
    )
    job = downloader.enqueue_from_records([_record("x")])[0]
    assert downloader.run_queue([job])[0]["status"] == "completed"
    before = store.media_states(job.source_id, collection_id="brazil26")[0]
    assert downloader.run_queue([job])[0]["status"] == "skipped"
    after = store.media_states(job.source_id, collection_id="brazil26")[0]
    assert before == after
    store.close()
