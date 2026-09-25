"""Regression coverage for permission-respecting TikTok capture-time media handoff."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.error import HTTPError

from laclaugpt_data_collection.capture_server import _complete_media_response
from laclaugpt_data_collection.cli import _apply_profile
from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.media import CaptureTimeMediaHandoff, MediaDownloader
from laclaugpt_data_collection.store import CollectionStore

MEDIA_URL = "https://v16-webapp-prime.tiktok.com/video/tos/useast2a/example"
SOURCE_URL = "https://www.tiktok.com/@synthetic/video/7300000000000000001"
BODY = b"synthetic-public-video-bytes"


def record() -> dict:
    return {
        "collection_id": "brazil26",
        "source_url": SOURCE_URL,
        "source": {"platform": "tiktok"},
        "content": {
            "media_references": [
                {"kind": "video", "url": MEDIA_URL, "media_index": 0},
            ]
        },
    }


def test_capture_before_record_reconciles_after_restart(tmp_path) -> None:
    first_store = CollectionStore(tmp_path)
    outcome = CaptureTimeMediaHandoff(first_store).capture(MEDIA_URL, BODY, "video/mp4")
    assert outcome["status"] == "pending_link"
    assert outcome["linked"] == 0
    first_store.close()

    second_store = CollectionStore(tmp_path)
    handoff = CaptureTimeMediaHandoff(second_store)
    assert handoff.register_record(record()) == 1
    jobs = MediaDownloader(second_store).enqueue_from_records([record()])
    assert jobs == []
    states = second_store.media_states(SOURCE_URL, collection_id="brazil26")
    assert len(states) == 1
    assert states[0]["status"] == "completed"
    assert states[0]["sha256"] == outcome["sha256"]
    assert states[0]["byte_size"] == len(BODY)
    assert (tmp_path / states[0]["local_path"]).read_bytes() == BODY
    second_store.close()


def test_record_before_capture_links_immediately_and_is_idempotent(tmp_path) -> None:
    store = CollectionStore(tmp_path)
    handoff = CaptureTimeMediaHandoff(store)
    assert handoff.register_record(record()) == 0

    first = handoff.capture(MEDIA_URL, BODY, "video/mp4")
    second = handoff.capture(MEDIA_URL, BODY, "video/mp4")
    assert first["status"] == second["status"] == "completed"
    assert first["linked"] == second["linked"] == 1
    assert first["sha256"] == second["sha256"]
    assert len(list((tmp_path / "media" / "captured").glob("*.mp4"))) == 1
    assert len(store.media_states(SOURCE_URL, collection_id="brazil26")) == 1
    store.close()


def test_tiktok_session_bound_403_is_terminal_for_detached_cron(tmp_path) -> None:
    store = CollectionStore(tmp_path)

    def denied(url: str):
        raise HTTPError(url, 403, "Forbidden", {}, None)

    downloader = MediaDownloader(store, workers=1, fetcher=denied)
    result = downloader.run_queue(downloader.enqueue_from_records([record()]))

    assert result[0]["status"] == "access_restricted"
    assert result[0]["http_status"] == 403
    assert downloader.enqueue_from_records([record()]) == []
    store.close()


def test_other_failures_remain_retryable(tmp_path) -> None:
    store = CollectionStore(tmp_path)

    def denied(url: str):
        raise HTTPError(url, 503, "Unavailable", {}, None)

    downloader = MediaDownloader(store, workers=1, fetcher=denied)
    result = downloader.run_queue(downloader.enqueue_from_records([record()]))

    assert result[0]["status"] == "failed"
    assert downloader.enqueue_from_records([record()])
    store.close()

def test_profile_download_media_flag_is_real_configuration(
    tmp_path: Path, monkeypatch
) -> None:
    profile = tmp_path / "brazil26.toml"
    profile.write_text(
        "[collector]\ndownload_media = true\nmedia_max_bytes = 12345\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("LACLAUGPT_CAPTURE_MEDIA_INLINE", raising=False)
    monkeypatch.delenv("LACLAUGPT_CAPTURE_MEDIA_MAX_BYTES", raising=False)

    _apply_profile(profile)
    settings = Settings(_env_file=None)

    assert settings.capture_media_inline is True
    assert settings.capture_media_max_bytes == 12345
    assert os.environ["LACLAUGPT_CAPTURE_MEDIA_INLINE"] == "True"

def test_partial_ranges_are_not_marked_as_complete() -> None:
    assert _complete_media_response(200, "", len(BODY))
    assert _complete_media_response(206, "bytes 0-27/28", 28)
    assert not _complete_media_response(206, "bytes 0-9/28", 10)
    assert not _complete_media_response(206, "bytes 10-27/28", 18)
    assert not _complete_media_response(403, "", 0)