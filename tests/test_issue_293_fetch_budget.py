"""Regression coverage for the AI26 fetch/store budget mismatch (#293).

Each cycle selected an 8-feed window at 5 items per feed (up to 40 candidates)
and then stored only the first `limit` records, so the tail of every fetch was
guaranteed to be discarded. The waste is removed by stopping the fetch at the
store's own stopping point; what the corpus receives must not change.

These tests pin both halves: the fetch now stops at the budget, and the stored
ids are byte-for-byte what the unbounded fetch produced.
"""
from __future__ import annotations

from datetime import UTC, datetime

from laclaugpt_data_collection import factory, server_runner
from laclaugpt_data_collection.collectors.base import CollectionResult
from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord
from laclaugpt_data_collection.realtime import parse_source_time

ABOVE_FLOOR = "2026-10-15T00:00:00Z"
BELOW_FLOOR = "2026-01-15T00:00:00Z"  # AI26 floor is 2026-09-01
FLOOR = datetime(2026, 9, 1, tzinfo=UTC)


class _FakeFeedCollector:
    """Deterministic stand-in for `RSSCollector`, one call per feed URL."""

    items: dict[str, list[str]] = {}
    calls: list[str] = []

    def __init__(self, feed_urls, *, max_items_per_feed, source_name):
        self.feed_url = feed_urls[0]
        self.max_items = max_items_per_feed
        self.source_name = source_name

    def collect(self):
        _FakeFeedCollector.calls.append(self.feed_url)
        stamps = _FakeFeedCollector.items.get(self.feed_url, [])[: self.max_items]
        result = CollectionResult(
            requests_seen=1, bodies_seen=1, raw_items_seen=len(stamps)
        )
        for index, stamp in enumerate(stamps):
            result.records.append(
                NormalizedRecord(
                    source_url=f"{self.feed_url}/{index}",
                    platform="rss",
                    text=f"{self.source_name} item {index}",
                    timestamp=stamp,
                    raw_payload={"index": index},
                    collection_provenance=CollectionProvenance(module="test-rss"),
                )
            )
        return result


class _MemoryStore:
    def __init__(self):
        self.ids: list[str] = []

    def upsert(self, record):
        self.ids.append(record.source_url)
        return True


def _feeds(count: int, *, items: int = 5) -> list[dict]:
    """A manifest-shaped window of `count` feeds, each carrying `items` records."""
    feeds = []
    _FakeFeedCollector.items = {}
    _FakeFeedCollector.calls = []
    for index in range(count):
        url = f"https://example.invalid/feed{index:02d}"
        feeds.append({"name": f"feed{index:02d}", "feed_url": url, "priority": "P1"})
        _FakeFeedCollector.items[url] = [ABOVE_FLOOR] * items
    return feeds


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        project_id="ai26",
        record_backend="csv",
        mongodb_uri="",
        object_backend="filesystem",
        cache_backend="memory",
        distributed_config_backend="local",
        messaging_backend="none",
        task_queue_backend="direct",
    )


def _run_cycle(monkeypatch, feeds, *, limit: int, max_feeds: int = 8, per_feed_limit: int = 5):
    store = _MemoryStore()
    monkeypatch.setattr(server_runner, "load_feed_manifest", lambda _path: feeds)
    monkeypatch.setattr(server_runner, "RSSCollector", _FakeFeedCollector)
    monkeypatch.setattr(factory, "build_record_store", lambda _settings: store)
    summary = server_runner.run_phase1_rss(
        _settings(),
        study_config="unused.yaml",
        source_manifest="synthetic.toml",
        collection_id="ai26",
        max_feeds=max_feeds,
        per_feed_limit=per_feed_limit,
        limit=limit,
        rotation=0,
    )
    return summary, store.ids


def _unbounded_stored_ids(feeds, *, limit: int, per_feed_limit: int = 5) -> list[str]:
    """The pre-#293 stored set: fetch the whole window, then keep the first `limit`.

    This is the old store loop, verbatim: skip records below the study floor,
    stop at `limit`. Any change to what the corpus receives shows up as a
    difference against this list.
    """
    records, _ = server_runner.collect_rss_records(
        feeds,
        collection_id="ai26",
        worker_id="reference",
        per_feed_limit=per_feed_limit,
    )
    stored: list[str] = []
    for record in records:
        published = parse_source_time(record.source.created_at)
        if published and published < FLOOR:
            continue
        if len(stored) >= limit:
            break
        stored.append(record.source_url)
    return stored


def test_fetch_stops_when_the_store_budget_is_full(monkeypatch):
    """8 feeds x 5 items, budget 20: four feeds are polled, not eight."""
    feeds = _feeds(8)
    summary, stored = _run_cycle(monkeypatch, feeds, limit=20)

    assert summary["feeds_considered"] == 8, "the window itself is unchanged"
    assert summary["feeds_polled"] == 4, "half of every cycle's HTTP was pure waste"
    assert len(_FakeFeedCollector.calls) == 4
    assert summary["records_collected"] == 20
    assert summary["records_synced"] == 20
    assert len(stored) == 20
    assert summary["fetch_stopped_early"] is True


def test_stored_set_is_identical_to_the_unbounded_fetch(monkeypatch):
    """The fix removes wasted fetch, it does not change what is stored."""
    feeds = _feeds(8)
    summary, stored = _run_cycle(monkeypatch, feeds, limit=20)

    assert stored == _unbounded_stored_ids(feeds, limit=20)
    assert stored == [f"https://example.invalid/feed{index:02d}/{item}" for index in range(4) for item in range(5)]
    assert summary["records_synced"] == len(stored)


def test_short_feeds_are_still_filled_from_later_feeds(monkeypatch):
    """A feed that yields less than `per_feed_limit` must not shrink the cycle."""
    feeds = _feeds(8)
    _FakeFeedCollector.items[feeds[0]["feed_url"]] = [ABOVE_FLOOR] * 2
    summary, stored = _run_cycle(monkeypatch, feeds, limit=20)

    assert len(stored) == 20
    assert stored == _unbounded_stored_ids(feeds, limit=20)
    assert summary["feeds_polled"] == 5, "18 from four feeds + 2 more to finish the budget"


def test_publication_floor_skips_do_not_consume_the_budget(monkeypatch):
    """Records the store skips for the floor must not count against the fetch."""
    feeds = _feeds(8)
    _FakeFeedCollector.items[feeds[0]["feed_url"]] = [BELOW_FLOOR, BELOW_FLOOR, ABOVE_FLOOR, ABOVE_FLOOR, ABOVE_FLOOR]
    summary, stored = _run_cycle(monkeypatch, feeds, limit=20)

    assert len(stored) == 20, "the cycle still stores a full budget"
    assert stored == _unbounded_stored_ids(feeds, limit=20)
    assert summary["skipped_before_publication_floor"] == 2
    assert summary["records_collected"] == len(stored) + 2
    assert summary["feeds_polled"] == 5


def test_fetch_never_exceeds_the_allocation(monkeypatch):
    """`records_collected` minus what the floor rejected never passes `limit`."""
    feeds = _feeds(8)
    _FakeFeedCollector.items[feeds[0]["feed_url"]] = [BELOW_FLOOR, ABOVE_FLOOR]
    summary, _stored = _run_cycle(monkeypatch, feeds, limit=20)

    budget_used = summary["records_collected"] - summary["skipped_before_publication_floor"]
    assert budget_used <= 20
    assert budget_used == summary["records_synced"]
    assert summary["feeds_polled"] <= 8


def test_a_window_smaller_than_the_budget_still_polls_every_feed(monkeypatch):
    feeds = _feeds(2)
    summary, stored = _run_cycle(monkeypatch, feeds, limit=20)

    assert summary["feeds_polled"] == 2
    assert summary["fetch_stopped_early"] is False
    assert len(stored) == 10
    assert len(_FakeFeedCollector.calls) == 2


def test_rotation_gives_every_feed_of_the_manifest_a_turn():
    """`select_feed_window` is what makes a bounded window fair over successive ticks."""
    manifest = [
        {"name": f"feed{index:02d}", "feed_url": f"https://example.invalid/{index}"}
        for index in range(32)
    ]
    windows = [
        [feed["name"] for feed in server_runner.select_feed_window(manifest, max_feeds=8, rotation=shift)]
        for shift in (0, 8, 16, 24)
    ]

    assert [len(window) for window in windows] == [8, 8, 8, 8]
    covered = [name for window in windows for name in window]
    assert len(set(covered)) == 32, "one full pass touches every manifest row exactly once"
    assert [name for name in covered if covered.count(name) > 1] == [], "no row is polled twice in a pass"


def test_rotation_keeps_priority_order_within_a_window():
    manifest = [
        {"name": "p2_a", "feed_url": "https://example.invalid/a", "priority": "P2"},
        {"name": "p1_a", "feed_url": "https://example.invalid/b", "priority": "P1"},
        {"name": "p3_a", "feed_url": "https://example.invalid/c", "priority": "P3"},
        {"name": "p1_b", "feed_url": "https://example.invalid/d", "priority": "P1"},
    ]
    window = [feed["name"] for feed in server_runner.select_feed_window(manifest, max_feeds=4, rotation=0)]
    assert window == ["p1_a", "p1_b", "p2_a", "p3_a"]

    rotated = [feed["name"] for feed in server_runner.select_feed_window(manifest, max_feeds=4, rotation=3)]
    assert rotated == ["p3_a", "p1_a", "p1_b", "p2_a"]
