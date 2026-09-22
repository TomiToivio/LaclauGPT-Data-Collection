"""Phase 1 Mastodon plugin contract for issue #107."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from laclaugpt_data_collection.collectors.mastodon import (
    MastodonCollectionError,
    MastodonCollector,
)
from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.models import CanonicalRecord
from laclaugpt_data_collection.plugins import CollectionContext, CollectionRunner, default_registry

STATUS = {
    "id": "899",
    "url": "https://social.example/@synthetic/899",
    "created_at": "2026-09-20T08:00:00Z",
    "language": "en",
    "content": "<p>Synthetic <strong>Mastodon</strong> status</p>",
    "account": {
        "acct": "synthetic",
        "username": "synthetic",
        "display_name": "Synthetic Researcher",
        "url": "https://social.example/@synthetic",
    },
    "media_attachments": [],
    "favourites_count": 4,
    "reblogs_count": 2,
    "replies_count": 1,
}


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def timeline_public(self, **kwargs):
        self.calls.append(kwargs)
        return [STATUS]

    def timeline_hashtag(self, hashtag, **kwargs):
        self.calls.append({"hashtag": hashtag, **kwargs})
        return [STATUS]


class MemoryStore:
    def __init__(self) -> None:
        self.records: dict[str, CanonicalRecord] = {}

    def contains(self, source_url: str) -> bool:
        return source_url in self.records

    def upsert(self, record: CanonicalRecord) -> None:
        self.records[record.source_url] = record

    def upsert_many(self, records: Iterable[CanonicalRecord]) -> None:
        for record in records:
            self.upsert(record)


def test_mastodon_cursor_raw_payload_identity_and_handoff() -> None:
    client = FakeClient()
    collector = MastodonCollector(
        "https://social.example",
        limit=10,
        cursor="900",
        client=client,
    )
    result = collector.collect()

    assert client.calls == [{"limit": 10, "max_id": "900"}]
    assert result.next_cursor == "899"
    assert len(result.records) == 1

    record = result.records[0]
    assert record.source_url == STATUS["url"]
    assert record.source_native_ids["document_id"] == "899"
    assert record.source.platform == "mastodon"
    assert record.content.text == "Synthetic Mastodon status"
    assert record.raw_capture.payload["id"] == "899"
    assert record.raw_capture.content_type == "application/json"
    assert record.analysis == {}

    handoff = build_handoff(record.model_dump(mode="json"), project_id="synthetic")
    assert handoff["status"] == "ready"
    assert handoff["source_url"] == STATUS["url"]


def test_mastodon_plugin_runner_is_idempotent_and_preserves_cursor(monkeypatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(MastodonCollector, "_client", lambda self: client)

    registry = default_registry()
    assert "mastodon" in registry.ids()

    store = MemoryStore()
    runner = CollectionRunner(registry, store)
    context = CollectionContext(
        config={"instance_url": "https://social.example", "limit": 5},
        collection_id="SYNTH26",
        cursor="900",
        run_id="run-107",
    )
    first = runner.run("mastodon", context)
    second = runner.run("mastodon", context)

    assert first.records_written == 1
    assert first.next_cursor == "899"
    assert second.records_written == 0
    assert second.duplicates_skipped == 1
    stored = store.records[STATUS["url"]]
    assert stored.source.raw_metadata["collection_id"] == "SYNTH26"
    assert stored.provenance[-1].metadata["cursor"] == "900"


def test_mastodon_rate_limit_exposes_retry_after_to_shared_orchestrator() -> None:
    class Response:
        status_code = 429
        headers = {"Retry-After": "7"}

    class RateLimited(RuntimeError):
        response = Response()

    class Client:
        def timeline_public(self, **kwargs):
            del kwargs
            raise RateLimited("too many requests")

    collector = MastodonCollector("https://social.example", client=Client())
    with pytest.raises(MastodonCollectionError) as captured:
        collector.collect()

    assert captured.value.retryable is True
    assert captured.value.retry_after == "7"
    assert captured.value.status_code == 429


def test_mastodon_deterministic_client_error_is_not_retryable() -> None:
    class Response:
        status_code = 400
        headers = {}

    class BadRequest(RuntimeError):
        response = Response()

    class Client:
        def timeline_public(self, **kwargs):
            del kwargs
            raise BadRequest("bad request")

    collector = MastodonCollector("https://social.example", client=Client())
    with pytest.raises(MastodonCollectionError) as captured:
        collector.collect()

    assert captured.value.retryable is False
    assert captured.value.status_code == 400
