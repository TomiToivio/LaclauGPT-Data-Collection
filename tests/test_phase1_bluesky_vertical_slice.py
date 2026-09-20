from __future__ import annotations

from typing import Any, Iterable

import httpx
import pytest

from laclaugpt_data_collection.collectors.bluesky import (
    BlueskyCollector,
    BlueskyRetryableError,
    BlueskyTerminalError,
)
from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.models import CanonicalRecord
from laclaugpt_data_collection.plugins import (
    CollectionContext,
    CollectionRunner,
    default_registry,
)


AT_URI = "at://did:plc:alice/app.bsky.feed.post/3kfixture"


def _post(*, cid: str = "bafy-fixture") -> dict[str, Any]:
    return {
        "uri": AT_URI,
        "cid": cid,
        "author": {
            "handle": "alice.example",
            "displayName": "Alice Example",
        },
        "record": {
            "text": "Synthetic Phase 1 Bluesky post",
            "createdAt": "2026-09-20T07:00:00Z",
            "langs": ["en"],
        },
        "indexedAt": "2026-09-20T07:00:05Z",
        "likeCount": 2,
        "replyCount": 1,
        "repostCount": 0,
        "quoteCount": 0,
    }


def _response(
    status: int,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    request = httpx.Request("GET", "https://public.api.bsky.app/xrpc/test")
    return httpx.Response(status, json=payload, headers=headers, request=request)


class FakeClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        self.calls.append(
            {
                "url": url,
                "params": dict(params),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


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


def test_mocked_xrpc_maps_to_stable_at_uri_and_preserves_resume_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        [
            _response(
                200,
                {
                    "posts": [_post()],
                    "cursor": "cursor-next",
                },
            )
        ]
    )
    monkeypatch.setattr(
        "laclaugpt_data_collection.collectors.bluesky.httpx.get",
        client.get,
    )

    plugin = default_registry().get("bluesky")
    result = plugin.collect(
        CollectionContext(
            config={"query": "AGI", "max_results": 1},
            project_id="ai26",
            collection_id="AI26",
            run_id="phase1-bluesky-test",
            cursor="cursor-resume",
        )
    )

    assert len(result.records) == 1
    assert result.next_cursor == "cursor-next"
    assert client.calls[0]["params"]["cursor"] == "cursor-resume"

    record = result.records[0]
    assert record.source_url == AT_URI
    assert record.dedup_key == AT_URI
    assert record.source_native_ids["document_id"] == AT_URI
    assert record.source.platform == "bluesky"
    assert record.source.source_type == "bluesky"
    assert record.content.text == "Synthetic Phase 1 Bluesky post"
    assert record.raw_capture.preserved

    source_provenance = record.provenance[0]
    assert source_provenance.api_url == AT_URI
    assert source_provenance.visited_url == (
        "https://bsky.app/profile/alice.example/post/3kfixture"
    )
    assert source_provenance.metadata["cid"] == "bafy-fixture"

    plugin_provenance = record.provenance[-1]
    assert plugin_provenance.module == "collection-plugin:bluesky"
    assert plugin_provenance.metadata["cursor"] == "cursor-resume"


def test_bluesky_uses_same_analysis_handoff_contract_as_other_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient([_response(200, {"posts": [_post()]})])
    monkeypatch.setattr(
        "laclaugpt_data_collection.collectors.bluesky.httpx.get",
        client.get,
    )
    record = default_registry().get("bluesky").collect(
        CollectionContext(
            config={"query": "AGI", "max_results": 1},
            collection_id="AI26",
        )
    ).records[0]

    handoff = build_handoff(record.model_dump(mode="json"))

    assert handoff["contract_version"] == "1.0"
    assert handoff["source_url"] == AT_URI
    assert handoff["collection_id"] == "AI26"
    assert handoff["handoff_key"]


def test_runner_deduplicates_repeated_bluesky_at_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        _response(200, {"posts": [_post(cid="cid-v1")]}),
        _response(200, {"posts": [_post(cid="cid-v2")]}),
    ]
    client = FakeClient(responses)
    monkeypatch.setattr(
        "laclaugpt_data_collection.collectors.bluesky.httpx.get",
        client.get,
    )

    store = MemoryStore()
    runner = CollectionRunner(default_registry(), store)
    context = CollectionContext(
        config={"query": "AGI", "max_results": 1},
        collection_id="AI26",
    )

    first = runner.run("bluesky", context)
    second = runner.run("bluesky", context)

    assert first.records_written == 1
    assert second.records_written == 0
    assert second.duplicates_skipped == 1
    assert list(store.records) == [AT_URI]


@pytest.mark.parametrize("status", [429, 500, 503])
def test_rate_limit_and_server_failures_are_retryable(
    status: int,
) -> None:
    headers = {"Retry-After": "17"} if status == 429 else {}
    collector = BlueskyCollector(
        query="AGI",
        max_results=1,
        client=FakeClient([_response(status, {"error": "synthetic"}, headers=headers)]),
    )

    with pytest.raises(BlueskyRetryableError) as captured:
        collector.collect()

    assert captured.value.retryable is True
    assert captured.value.status_code == status
    if status == 429:
        assert captured.value.retry_after == "17"


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_failures_are_terminal(status: int) -> None:
    collector = BlueskyCollector(
        query="AGI",
        max_results=1,
        client=FakeClient([_response(status, {"error": "synthetic"})]),
    )

    with pytest.raises(BlueskyTerminalError) as captured:
        collector.collect()

    assert captured.value.retryable is False
    assert captured.value.status_code == status


def test_transport_failure_is_retryable() -> None:
    class BrokenClient:
        def get(self, url: str, **kwargs: Any) -> httpx.Response:
            request = httpx.Request("GET", url)
            raise httpx.ConnectError("synthetic outage", request=request)

    collector = BlueskyCollector(query="AGI", max_results=1, client=BrokenClient())

    with pytest.raises(BlueskyRetryableError) as captured:
        collector.collect()

    assert captured.value.retryable is True
    assert captured.value.status_code is None
