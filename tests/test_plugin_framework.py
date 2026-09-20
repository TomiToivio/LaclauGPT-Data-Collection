from collections.abc import Iterable

import pytest

from laclaugpt_data_collection.collectors.base import CollectionResult
from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.models import CanonicalRecord, NormalizedRecord
from laclaugpt_data_collection.plugins import (
    CollectionContext,
    CollectionRunner,
    PluginRegistry,
    PluginSpec,
    adapt_collector,
    default_registry,
)


class SyntheticCollector:
    def __init__(self, record: NormalizedRecord, *, next_cursor: str | None = None) -> None:
        self.record = record
        self.next_cursor = next_cursor

    def collect(self) -> CollectionResult:
        return CollectionResult(
            records=[self.record],
            raw_items_seen=1,
            next_cursor=self.next_cursor,
        )


class MemoryStore:
    def __init__(self, events: list[tuple[str, str]] | None = None) -> None:
        self.records: dict[str, CanonicalRecord] = {}
        self.events = events if events is not None else []

    def contains(self, source_url: str) -> bool:
        return source_url in self.records

    def upsert(self, record: CanonicalRecord) -> None:
        self.records[record.source_url] = record
        self.events.append(("store", record.source_url))

    def upsert_many(self, records: Iterable[CanonicalRecord]) -> None:
        for record in records:
            self.upsert(record)


def _record(platform: str, source_url: str) -> NormalizedRecord:
    return NormalizedRecord(
        document_id=f"{platform}-1",
        platform=platform,
        source_url=source_url,
        text=f"synthetic {platform} item",
        raw_payload={"platform": platform, "synthetic": True},
        raw_content_type="application/json",
    )


def _plugin(plugin_id: str, source_type: str, source_url: str):
    spec = PluginSpec(
        plugin_id=plugin_id,
        version="1.2.3",
        source_type=source_type,
        config_schema={"type": "object"},
        modes=("batch",),
    )
    return adapt_collector(spec, lambda _context: SyntheticCollector(_record(source_type, source_url)))


def test_two_plugins_emit_same_canonical_handoff_contract() -> None:
    registry = PluginRegistry()
    registry.register(_plugin("synthetic-feed", "rss", "https://example.invalid/feed/1"))
    registry.register(_plugin("synthetic-api", "bluesky", "at://did:example/post/1"))
    context = CollectionContext(
        project_id="synthetic-project",
        collection_id="SYNTH26",
        arena="public-example",
        run_id="run-1",
        privacy={"access": "research-only", "publish_raw": False},
    )

    records = []
    for plugin_id in registry.ids():
        result = registry.get(plugin_id).collect(context)
        assert len(result.records) == 1
        record = result.records[0]
        records.append(record)
        assert record.raw_capture.preserved
        assert record.source.source_type in {"rss", "bluesky"}
        assert record.source.raw_metadata["collection_id"] == "SYNTH26"
        assert record.provenance[-1].module == f"collection-plugin:{plugin_id}"
        assert record.provenance[-1].metadata["privacy"]["access"] == "research-only"

    assert records[0].schema_version == records[1].schema_version
    handoffs = [build_handoff(record.model_dump(mode="json")) for record in records]
    assert {handoff["contract_version"] for handoff in handoffs} == {"1.0"}
    assert {handoff["collection_id"] for handoff in handoffs} == {"SYNTH26"}


def test_runner_persists_before_notification_and_repeated_run_is_idempotent() -> None:
    events: list[tuple[str, str]] = []
    store = MemoryStore(events)
    registry = PluginRegistry()
    source_url = "https://example.invalid/item/42"
    registry.register(_plugin("synthetic", "api", source_url))
    runner = CollectionRunner(registry, store)

    def notify(record: CanonicalRecord) -> None:
        events.append(("notify", record.source_url))

    first = runner.run(
        "synthetic",
        CollectionContext(collection_id="SYNTH26", run_id="run-1"),
        notify=notify,
    )
    assert first.records_written == 1
    assert first.duplicates_skipped == 0
    assert events == [("store", source_url), ("notify", source_url)]

    second = runner.run(
        "synthetic",
        CollectionContext(collection_id="SYNTH26", run_id="run-2"),
        notify=notify,
    )
    assert second.records_written == 0
    assert second.duplicates_skipped == 1
    assert events == [("store", source_url), ("notify", source_url)]


def test_runner_accepts_resume_cursor_and_returns_next_checkpoint() -> None:
    observed_cursors: list[str | None] = []
    spec = PluginSpec(
        plugin_id="cursor-source",
        version="1.0.0",
        source_type="api",
        modes=("polling",),
    )

    def factory(context: CollectionContext) -> SyntheticCollector:
        observed_cursors.append(context.cursor)
        return SyntheticCollector(
            _record("api", "urn:synthetic:cursor-item"),
            next_cursor="cursor-2",
        )

    registry = PluginRegistry()
    registry.register(adapt_collector(spec, factory))
    runner = CollectionRunner(registry, MemoryStore())
    result = runner.run(
        "cursor-source",
        CollectionContext(collection_id="SYNTH26", cursor="cursor-1"),
    )

    assert observed_cursors == ["cursor-1"]
    assert result.next_cursor == "cursor-2"


def test_default_registry_is_lazy_and_declares_versioned_source_contracts() -> None:
    specs = {spec.plugin_id: spec for spec in default_registry().specs()}
    assert set(specs) == {"arxiv", "bluesky", "mastodon", "rss"}
    assert specs["rss"].version == "1.0.0"
    assert "feed_urls" in specs["rss"].config_schema["required"]
    assert "polling" in specs["bluesky"].modes
    assert "batch" in specs["arxiv"].modes


def test_missing_plugin_configuration_fails_before_collection() -> None:
    plugin = default_registry().get("rss")
    with pytest.raises(ValueError, match="feed_urls"):
        plugin.collect(CollectionContext())


def test_duplicate_plugin_ids_are_rejected() -> None:
    registry = PluginRegistry()
    plugin = _plugin("synthetic", "api", "urn:synthetic:1")
    registry.register(plugin)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(plugin)
