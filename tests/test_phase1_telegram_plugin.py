"""Phase 1 Telegram plugin contract for issue #109."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from laclaugpt_data_collection import plugins
from laclaugpt_data_collection.collectors.telegram import map_message
from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.models import CanonicalRecord

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "telegram_messages_v1.json").read_text(
        encoding="utf-8"
    )
)


class FakeMessage:
    def __init__(self, payload: dict) -> None:
        self._payload = dict(payload)
        self.id = payload["id"]
        self.raw_text = payload["raw_text"]
        self.text = payload["text"]
        self.date = payload["date"]
        self.peer_id = SimpleNamespace(channel_id=payload["channel_id"])
        self.media = object() if payload["media"] else None

    def to_dict(self) -> dict:
        return dict(self._payload)


class FakeClient:
    def __init__(self, messages: list[dict] | None = None) -> None:
        self.messages = list(messages or FIXTURE["messages"])
        self.calls: list[tuple[str, dict]] = []

    def get_messages(self, channel: str, **kwargs):
        self.calls.append((channel, kwargs))
        return [FakeMessage(item) for item in self.messages]


class MemoryStore:
    def __init__(self) -> None:
        self.records: dict[str, CanonicalRecord] = {}

    def contains(self, source_url: str) -> bool:
        return source_url in self.records

    def upsert(self, record: CanonicalRecord) -> None:
        self.records[record.source_url] = record


def test_telegram_plugin_maps_fixture_cursor_raw_identity_and_handoff() -> None:
    client = FakeClient()
    registry = plugins.default_registry()
    assert "telegram" in registry.ids()
    spec = registry.get("telegram").spec
    assert spec.version == "1.0.0"
    assert "pre-authenticated session" in spec.authentication

    plugin = registry.get("telegram")
    result = plugin.collect(
        plugins.CollectionContext(
            config={
                "channel": FIXTURE["channel"],
                "limit": 2,
                "_client": client,
                "raw_ref_prefix": "fixture://telegram/raw",
            },
            collection_id="SYNTH26",
            run_id="run-109",
            cursor="903",
        )
    )

    assert client.calls == [(FIXTURE["channel"], {"limit": 2, "max_id": 903})]
    assert result.next_cursor == "901"
    assert len(result.records) == 2

    media_record, text_record = result.records
    assert media_record.source_url == "https://t.me/synthetic_channel/902"
    assert media_record.source_native_ids["telegram_message_id"] == "902"
    assert media_record.source_native_ids["telegram_channel_id"] == "123456"
    assert media_record.raw_capture.payload == FIXTURE["messages"][0]
    assert media_record.raw_capture.ref == "fixture://telegram/raw/synthetic_channel/902.json"
    assert media_record.content.media_references[0].metadata["download_required"] is True
    assert media_record.analysis == {}

    assert text_record.source_url == "https://t.me/synthetic_channel/901"
    assert text_record.raw_capture.payload == FIXTURE["messages"][1]
    handoff = build_handoff(text_record.model_dump(mode="json"), project_id="synthetic")
    assert handoff["contract_version"] == "1.0"
    assert handoff["source_url"] == text_record.source_url
    assert handoff["collection_id"] == "SYNTH26"
    assert handoff["status"] == "ready"


def test_telegram_non_web_target_uses_stable_uri_identity() -> None:
    message = FakeMessage(FIXTURE["messages"][1])
    record = map_message(message, channel="@PrivateSyntheticChannel")
    assert record is not None
    assert record.source_url == "telegram:privatesyntheticchannel:901"


def test_telegram_runner_is_idempotent() -> None:
    client = FakeClient()
    registry = plugins.default_registry()
    store = MemoryStore()
    runner = plugins.CollectionRunner(registry, store)
    context = plugins.CollectionContext(
        config={"channel": FIXTURE["channel"], "_client": client, "limit": 2},
        collection_id="SYNTH26",
        cursor="903",
    )

    first = runner.run("telegram", context)
    second = runner.run("telegram", context)

    assert first.records_written == 2
    assert first.duplicates_skipped == 0
    assert first.next_cursor == "901"
    assert second.records_written == 0
    assert second.duplicates_skipped == 2
    assert len(store.records) == 2


def test_telegram_flood_wait_uses_shared_bounded_retry() -> None:
    class FloodWaitError(RuntimeError):
        seconds = 90

    class FlakyClient(FakeClient):
        def __init__(self) -> None:
            super().__init__([FIXTURE["messages"][1]])
            self.attempts = 0

        def get_messages(self, channel: str, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise FloodWaitError("synthetic flood wait")
            return super().get_messages(channel, **kwargs)

    client = FlakyClient()
    sleeps: list[float] = []
    runner = plugins.CollectionRunner(
        plugins.default_registry(),
        MemoryStore(),
        retry_policy=plugins.RetryPolicy(max_attempts=2, base_delay_seconds=1, max_delay_seconds=5),
        sleep=sleeps.append,
    )

    result = runner.run(
        "telegram",
        plugins.CollectionContext(
            config={"channel": FIXTURE["channel"], "_client": client, "limit": 1},
            collection_id="SYNTH26",
        ),
    )

    assert client.attempts == 2
    assert sleeps == [5]
    assert result.attempts == 2
    assert result.records_written == 1
