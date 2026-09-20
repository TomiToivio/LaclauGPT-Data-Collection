"""Phase 1 YouTube plugin contract for issue #108."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from laclaugpt_data_collection import plugins
from laclaugpt_data_collection.collectors.youtube import (
    YouTubeCollectionError,
    YouTubeCollector,
)
from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.models import CanonicalRecord

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "youtube_videos_v1.json").read_text(
        encoding="utf-8"
    )
)


class MemoryStore:
    def __init__(self) -> None:
        self.records: dict[str, CanonicalRecord] = {}

    def contains(self, source_url: str) -> bool:
        return source_url in self.records

    def upsert(self, record: CanonicalRecord) -> None:
        self.records[record.source_url] = record


def _loader_by_url(url: str) -> dict:
    suffix = "synthetic002" if "synthetic002" in url else "synthetic001"
    return next(item for item in FIXTURE["videos"] if item["id"] == suffix)


def test_youtube_plugin_maps_fixture_identity_raw_reference_and_handoff() -> None:
    registry = plugins.default_registry()
    assert "youtube" in registry.ids()
    spec = registry.get("youtube").spec
    assert spec.version == "1.0.0"
    assert "Data Analysis" in spec.media_policy

    plugin = registry.get("youtube")
    result = plugin.collect(
        plugins.CollectionContext(
            config={
                "video_urls": [
                    "https://youtu.be/synthetic001",
                    "https://www.youtube.com/watch?v=synthetic002",
                ],
                "page_size": 1,
                "raw_ref_prefix": "fixture://youtube/raw",
                "_info_loader": _loader_by_url,
            },
            collection_id="SYNTH26",
            run_id="run-108",
        )
    )

    assert result.next_cursor == "1"
    assert len(result.records) == 1
    record = result.records[0]
    assert record.source_url == "https://www.youtube.com/watch?v=synthetic001"
    assert record.source_native_ids["document_id"] == "synthetic001"
    assert record.raw_capture.payload == FIXTURE["videos"][0]
    assert record.raw_capture.ref == "fixture://youtube/raw/synthetic001.json"
    assert record.content.title == "Synthetic AI research briefing"
    assert record.content.media_references[0].ref == record.source_url
    assert record.content.media_references[0].url == ""
    assert record.content.media_references[0].metadata["download_required"] is False
    assert record.content.media_references[0].metadata["resolve_media_downstream"] is True
    assert record.content.transcripts == []
    assert record.intermediate.asr == []
    assert record.intermediate.frames == []
    assert record.analysis == {}

    handoff = build_handoff(record.model_dump(mode="json"), project_id="synthetic")
    assert handoff["status"] == "ready"
    assert handoff["source_url"] == record.source_url
    assert handoff["collection_id"] == "SYNTH26"


def test_youtube_cursor_paginates_and_runner_is_idempotent() -> None:
    registry = plugins.default_registry()
    store = MemoryStore()
    runner = plugins.CollectionRunner(registry, store)
    config = {
        "video_urls": [
            "https://youtu.be/synthetic001",
            "https://youtu.be/synthetic002",
        ],
        "page_size": 1,
        "_info_loader": _loader_by_url,
    }

    first = runner.run(
        "youtube",
        plugins.CollectionContext(config=config, collection_id="SYNTH26"),
    )
    second_page = runner.run(
        "youtube",
        plugins.CollectionContext(
            config=config,
            collection_id="SYNTH26",
            cursor=first.next_cursor,
        ),
    )
    repeated_second_page = runner.run(
        "youtube",
        plugins.CollectionContext(
            config=config,
            collection_id="SYNTH26",
            cursor=first.next_cursor,
        ),
    )

    assert first.records_written == 1
    assert first.next_cursor == "1"
    assert second_page.records_written == 1
    assert second_page.next_cursor is None
    assert repeated_second_page.records_written == 0
    assert repeated_second_page.duplicates_skipped == 1
    assert len(store.records) == 2


def test_youtube_rate_limit_uses_shared_bounded_retry() -> None:
    attempts = 0

    class Response:
        status_code = 429
        headers = {"Retry-After": "4"}

    class RateLimited(RuntimeError):
        response = Response()

    def flaky_loader(url: str) -> dict:
        nonlocal attempts
        del url
        attempts += 1
        if attempts == 1:
            raise RateLimited("429 Too Many Requests")
        return FIXTURE["videos"][0]

    sleeps: list[float] = []
    runner = plugins.CollectionRunner(
        plugins.default_registry(),
        MemoryStore(),
        retry_policy=plugins.RetryPolicy(
            max_attempts=2,
            base_delay_seconds=1,
            max_delay_seconds=10,
        ),
        sleep=sleeps.append,
    )
    result = runner.run(
        "youtube",
        plugins.CollectionContext(
            config={
                "video_urls": ["https://youtu.be/synthetic001"],
                "_info_loader": flaky_loader,
            }
        ),
    )

    assert attempts == 2
    assert sleeps == [4]
    assert result.attempts == 2
    assert result.records_written == 1


def test_youtube_quota_error_is_terminal() -> None:
    def quota_loader(url: str) -> dict:
        del url
        raise RuntimeError("403 quota exceeded")

    collector = YouTubeCollector(
        ["https://youtu.be/synthetic001"],
        info_loader=quota_loader,
    )
    with pytest.raises(YouTubeCollectionError) as captured:
        collector.collect()

    assert captured.value.retryable is False
    assert captured.value.status_code == 403
    assert captured.value.reason == "quota_exceeded"


def test_youtube_invalid_cursor_fails_before_network() -> None:
    collector = YouTubeCollector(
        ["https://youtu.be/synthetic001"],
        cursor="not-an-offset",
        info_loader=_loader_by_url,
    )
    with pytest.raises(ValueError, match="non-negative integer offset"):
        collector.collect()
