# -*- coding: utf-8 -*-
"""Issue #293, fairness half: a bounded RSS cycle must also be a *fair* one.

#301 stopped the cycle fetching more records than it can store. This pins what
the issue still names: with a 4-feed window over a 32-feed manifest, every feed
must get a turn within a bounded number of cycles, none may be permanently
starved, the sequence must be reproducible from the same start state, and the
rotation must be *visible* in the cycle log so per-feed cadence can be verified
from the log rather than inferred from `captured_at` timestamps.

The bound is computed from the shipping code, not asserted from taste. With the
runner defaults (limit=40, max_jobs=6, per_source_limit=5):

    non_browser_reserve = min(limit // 2, max_jobs * per_source_limit) = 20
    rss_allocation      = limit - non_browser_reserve                  = 20
    feed window         = min(max_feeds=8, rss_allocation // 5)        =  4
    window advance      = the window size, per hourly cycle            =  4

so a 32-feed manifest is covered by ceil(32 / 4) = 8 cycles: worst-case per-feed
cadence 8 cycles = 8 hours, and a feed added at the tail of the manifest waits at
most one pass (8 h) for its first record, not ~a day.
"""
from __future__ import annotations

import math

from laclaugpt_data_collection import ai26_laskin_runner as runner
from laclaugpt_data_collection import factory, server_runner
from laclaugpt_data_collection.collectors.base import CollectionResult
from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord

ABOVE_FLOOR = "2026-10-15T00:00:00Z"
MANIFEST_FEEDS = 32
ITEMS_PER_FEED = 5
RSS_LIMIT = 20  # the default `rss_allocation`
WINDOW = RSS_LIMIT // ITEMS_PER_FEED  # 4


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


def _manifest(count: int = MANIFEST_FEEDS, *, items: int = ITEMS_PER_FEED) -> list[dict]:
    """A 32-row manifest shaped like the real one: same priority, manifest order."""
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


def _cycle(monkeypatch, feeds, *, rotation: int) -> tuple[dict, list[str]]:
    """Run one real `run_phase1_rss` cycle, with the rotation the runner computes."""
    store = _MemoryStore()
    monkeypatch.setattr(server_runner, "load_feed_manifest", lambda _path: feeds)
    monkeypatch.setattr(server_runner, "RSSCollector", _FakeFeedCollector)
    monkeypatch.setattr(factory, "build_record_store", lambda _settings: store)
    summary = server_runner.run_phase1_rss(
        _settings(),
        study_config="unused.yaml",
        source_manifest="synthetic.toml",
        collection_id="ai26",
        max_feeds=WINDOW,
        per_feed_limit=ITEMS_PER_FEED,
        limit=RSS_LIMIT,
        rotation=rotation,
    )
    return summary, store.ids


def _pass(monkeypatch, feeds, *, cycles: int) -> list[dict]:
    """Consecutive cycles, advancing the window exactly as `run_phase1_laskin` does."""
    return [_cycle(monkeypatch, feeds, rotation=cycle * WINDOW)[0] for cycle in range(cycles)]


def test_every_feed_is_polled_within_one_bounded_pass(monkeypatch):
    """8 cycles over 32 feeds: every feed polled once, none twice, per cycle 4."""
    feeds = _manifest()
    summaries = _pass(monkeypatch, feeds, cycles=math.ceil(MANIFEST_FEEDS / WINDOW))

    polled = [name for summary in summaries for name in summary["feeds_polled_names"]]
    assert len(polled) == MANIFEST_FEEDS
    assert set(polled) == {feed["name"] for feed in feeds}, "no feed may be starved"
    assert len(set(polled)) == MANIFEST_FEEDS, "one pass touches each feed exactly once"
    for summary in summaries:
        assert len(summary["feeds_polled_names"]) == WINDOW


def test_no_feed_is_starved_across_repeated_passes(monkeypatch):
    """A second pass must poll every feed again, at the same bounded gap."""
    feeds = _manifest()
    cycles = 2 * math.ceil(MANIFEST_FEEDS / WINDOW)
    summaries = _pass(monkeypatch, feeds, cycles=cycles)

    polled_at: dict[str, list[int]] = {}
    for index, summary in enumerate(summaries):
        for name in summary["feeds_polled_names"]:
            polled_at.setdefault(name, []).append(index)

    assert set(polled_at) == {feed["name"] for feed in feeds}
    for name, indexes in polled_at.items():
        assert len(indexes) == 2, f"{name} must be polled once per pass"
        assert indexes[1] - indexes[0] == WINDOW * 2, (
            f"{name} has an unbounded gap of {indexes[1] - indexes[0]} cycles"
        )
    # The worst case over all feeds is the whole pass, never more.
    worst = max(indexes[1] - indexes[0] for indexes in polled_at.values())
    assert worst == 8, f"32 feeds / 4 per cycle is 8 cycles, measured {worst}"


def test_the_rotation_is_deterministic_from_the_same_start_state():
    """Same manifest and same start position produce the same sequence of windows."""
    feeds = _manifest()
    first = [
        [feed["name"] for feed in server_runner.select_feed_window(feeds, max_feeds=WINDOW, rotation=cycle * WINDOW)]
        for cycle in range(8)
    ]
    second = [
        [feed["name"] for feed in server_runner.select_feed_window(feeds, max_feeds=WINDOW, rotation=cycle * WINDOW)]
        for cycle in range(8)
    ]

    assert first == second
    assert first == [
        [f"feed{index:02d}" for index in range(start, start + WINDOW)]
        for start in range(0, MANIFEST_FEEDS, WINDOW)
    ], "consecutive windows must partition the priority-ordered manifest"
    assert sum(first, []) == [feed["name"] for feed in feeds]


def test_stored_set_per_cycle_is_unchanged_in_size(monkeypatch):
    """The rotation moves which feeds are polled, never how much is stored."""
    feeds = _manifest()
    sizes = []
    for cycle in range(8):
        summary, stored = _cycle(monkeypatch, feeds, rotation=cycle * WINDOW)
        sizes.append(len(stored))
        assert summary["records_synced"] == RSS_LIMIT
        assert summary["feeds_considered"] == WINDOW
        assert len(stored) == len(set(stored)), "a cycle must not store duplicates"

    assert sizes == [RSS_LIMIT] * 8, "every cycle stores exactly the rss_allocation"
    assert sum(sizes) == 8 * RSS_LIMIT, "the daily volume is bounded, not raised"


def test_the_cycle_log_exposes_the_window_position_and_polled_feeds(monkeypatch):
    """Cadence must be verifiable from the log, not inferred from timestamps."""
    feeds = _manifest()
    summary, _stored = _cycle(monkeypatch, feeds, rotation=3 * WINDOW)

    assert summary["feeds_in_manifest"] == MANIFEST_FEEDS
    assert summary["feed_window_rotation"] == 3 * WINDOW, "the window position is logged"
    assert summary["feed_names"] == [f"feed{index:02d}" for index in range(12, 16)]
    assert summary["feeds_polled_names"] == summary["feed_names"]
    assert summary["feeds_polled"] == WINDOW


def test_the_runner_derives_the_four_feed_window_and_its_step(monkeypatch, tmp_path):
    """The bound must come from `run_phase1_laskin`, not from this test's arithmetic."""
    captured: dict = {}

    class Sink:
        notification_errors = []

        def __init__(self, settings):
            pass

        def assert_private_config(self, path):
            pass

    def rss(*args, **kwargs):
        captured.update(kwargs)
        return {
            "records_synced": kwargs["limit"],
            "records_new": 0,
            "feed_names": [f"feed{index:02d}" for index in range(4)],
            "feeds_polled_names": [f"feed{index:02d}" for index in range(4)],
            "feeds_in_manifest": MANIFEST_FEEDS,
            "feed_window_rotation": kwargs["rotation"],
        }

    monkeypatch.setattr(runner, "DistributedCaptureSink", Sink)
    monkeypatch.setattr(runner, "load_non_browser_jobs", lambda path: [{"kind": "web_source", "name": "j"}])
    monkeypatch.setattr(runner, "preflight_optional_dependencies", lambda jobs: [])
    monkeypatch.setattr(runner, "run_phase1_rss", rss)
    monkeypatch.setattr(runner, "_records_for_job", lambda row, **kwargs: ([], []))

    result = runner.run_phase1_laskin(
        Settings(_env_file=None, project_id="ai26"),
        study_config=tmp_path / "study.yaml",
        source_manifest=tmp_path / "sources.toml",
        rotation=7,
        limit=40,
        max_jobs=6,
        per_source_limit=5,
    )

    assert captured["limit"] == 20, "rss_allocation stays 20; the fix does not raise throughput"
    assert captured["max_feeds"] == 4, "the window is sized to the store budget"
    assert captured["rotation"] == 7 * 4, "the window advances by its own size, per cycle"

    window = result["tick_budget"]["rss_feed_window"]
    assert window["window_size"] == 4
    assert window["feeds_in_manifest"] == MANIFEST_FEEDS
    assert window["cycles_per_pass"] == 8, "ceil(32 / 4): the worst-case cadence, in cycles"
    assert window["polled"] == window["window"]
    assert result["tick_budget"]["rss_allocation"] == 20
