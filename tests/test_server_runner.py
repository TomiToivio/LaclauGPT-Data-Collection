from pathlib import Path

import pytest

from laclaugpt_data_collection.collectors.base import CollectionResult
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord
from laclaugpt_data_collection.realtime import parse_source_time
from laclaugpt_data_collection.server_runner import (
    Phase0MongoStore,
    load_feed_manifest,
    phase0_collection_name,
    phase0_document,
    run_distributed_rss,
    select_feed_window,
)


class FakeStore:
    last = None

    def __init__(self, uri, database, project_id, **kwargs):
        self.uri = uri
        self.database = database
        self.project_id = project_id
        self.collection_name = f"laclaugpt2_{project_id}_scraper_collection"
        self.records = []
        FakeStore.last = self

    def upsert(self, record):
        self.records.append(record)


class FakeRSSCollector:
    def __init__(self, feed_urls, *, max_items_per_feed=100):
        self.feed_url = feed_urls[0]
        self.max_items_per_feed = max_items_per_feed

    def collect(self):
        records = [
            NormalizedRecord(
                document_id="new",
                platform="rss",
                timestamp="Wed, 16 Sep 2026 10:00:00 GMT",
                source_url=f"{self.feed_url}/new",
                text="new item",
                raw_payload={"id": "new"},
                collection_provenance=CollectionProvenance(module="rss-test"),
            ),
            NormalizedRecord(
                document_id="old",
                platform="rss",
                timestamp="Mon, 31 Aug 2026 10:00:00 GMT",
                source_url=f"{self.feed_url}/old",
                text="old item",
                raw_payload={"id": "old"},
                collection_provenance=CollectionProvenance(module="rss-test"),
            ),
        ]
        return CollectionResult(records=records, requests_seen=1, bodies_seen=1, raw_items_seen=2)


class SettingsStub:
    project_id = "ai26"
    mongodb_uri = "mongodb://example.invalid"
    mongodb_database = "laclaugpt"
    effective_mongodb_collection = "ai26_records"
    mongodb_connect_timeout_ms = 2000
    mongodb_graph_max_depth = 3


def test_manifest_loader_uses_feed_array(tmp_path: Path) -> None:
    path = tmp_path / "sources.toml"
    path.write_text(
        '[[feed]]\nname="one"\nfeed_url="https://example.org/feed"\npriority="P1"\n',
        encoding="utf-8",
    )
    assert load_feed_manifest(path) == [
        {"name": "one", "feed_url": "https://example.org/feed", "priority": "P1"}
    ]


def _feed(name: str, priority: str, url: str = "https://example.org/feed") -> dict:
    return {"name": name, "feed_url": url, "priority": priority}


def test_feed_window_prefers_high_priority_and_bounds_the_batch() -> None:
    feeds = [
        _feed("late", "P3"),
        _feed("first", "P1"),
        _feed("second", "P2"),
        _feed("third", "P1"),
    ]
    window = select_feed_window(feeds, max_feeds=2)
    assert [feed["name"] for feed in window] == ["first", "third"]


def test_feed_window_equal_priority_keeps_manifest_order() -> None:
    feeds = [_feed("a", "P1"), _feed("b", "P1"), _feed("c", "P1")]
    window = select_feed_window(feeds, max_feeds=2)
    assert [feed["name"] for feed in window] == ["a", "b"]


def test_feed_window_rotation_eventually_covers_the_whole_manifest() -> None:
    feeds = [_feed(f"f{index}", "P1") for index in range(6)]
    seen: set[str] = set()
    # 6 feeds / window of 2 = 3 distinct offsets before the rotation wraps.
    for step in range(3):
        window = select_feed_window(feeds, max_feeds=2, rotation=step * 2)
        seen.update(feed["name"] for feed in window)
    # Every manifest entry is polled across one rotation; a plain
    # feeds[:max_feeds] slice would only ever yield f0 and f1.
    assert seen == {f"f{index}" for index in range(6)}


def test_feed_window_rotation_wraps_instead_of_starving_tail() -> None:
    feeds = [_feed(f"f{index}", "P1") for index in range(6)]
    # Offsets beyond the manifest length wrap rather than returning nothing.
    assert len(select_feed_window(feeds, max_feeds=2, rotation=8)) == 2


def test_feed_window_rejects_non_positive_window() -> None:
    with pytest.raises(ValueError, match="max_feeds must be at least 1"):
        select_feed_window([_feed("a", "P1")], max_feeds=0)


def test_rfc_rss_timestamp_is_supported() -> None:
    parsed = parse_source_time("Wed, 16 Sep 2026 10:00:00 GMT")
    assert parsed is not None
    assert parsed.isoformat() == "2026-09-16T10:00:00+00:00"


def test_phase0_rss_upserts_directly_to_mongodb(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = tmp_path / "sources.toml"
    manifest.write_text(
        '[[feed]]\nname="one"\nfeed_url="https://example.org/feed"\n'
        'source_family="synthetic"\narena="elites"\npriority="P1"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("laclaugpt_data_collection.server_runner.Phase0MongoStore", FakeStore)
    monkeypatch.setattr("laclaugpt_data_collection.server_runner.RSSCollector", FakeRSSCollector)

    result = run_distributed_rss(
        SettingsStub(),
        source_manifest=manifest,
        collection_id="ai26",
        max_feeds=1,
        per_feed_limit=2,
        limit=1,
        rotation=0,
    )
    assert result["records_collected"] == 2
    assert result["records_synced"] == 1
    assert result["mongodb_collection"] == "laclaugpt2_ai26_scraper_collection"
    assert "duplicate_leases" not in result
    assert FakeStore.last is not None
    stored = FakeStore.last.records[0]
    assert stored.source.raw_metadata["collection_id"] == "ai26"
    assert stored.source.raw_metadata["source_name"] == "one"
    assert stored.source.raw_metadata["arena"] == "elites"
    assert stored.provenance[-1].metadata["worker_id"] == "linux-server-rss"


def test_phase0_rss_requires_mongodb(tmp_path: Path) -> None:
    manifest = tmp_path / "sources.toml"
    manifest.write_text(
        '[[feed]]\nname="one"\nfeed_url="https://example.org/feed"\n',
        encoding="utf-8",
    )

    class MissingMongo(SettingsStub):
        mongodb_uri = ""

    with pytest.raises(RuntimeError, match="requires LACLAUGPT_MONGODB_URI"):
        run_distributed_rss(MissingMongo(), source_manifest=manifest)


def test_phase0_collection_name_matches_analysis_contract() -> None:
    assert phase0_collection_name("ai26") == "laclaugpt2_ai26_scraper_collection"


def test_phase0_document_is_flat_and_analysis_ready() -> None:
    record = NormalizedRecord(
        document_id="article-1",
        platform="rss",
        timestamp="Wed, 16 Sep 2026 10:00:00 GMT",
        source_url="https://example.org/article",
        text="Article body",
        author="Alice",
        raw_payload={"id": "article-1"},
        collection_provenance=CollectionProvenance(module="rss-test"),
    )
    record.content.title = "Article title"
    record.source.raw_metadata["source_name"] = "Example Feed"
    record.source.raw_metadata["arena"] = "elites"

    document = phase0_document(record)

    assert document == {
        "document_id": "article-1",
        "source_url": "https://example.org/article",
        "source_text": "Article body",
        "source_title": "Article title",
        "title": "Article title",
        "source_date": "Wed, 16 Sep 2026 10:00:00 GMT",
        "source_name": "Example Feed",
        "source_type": "rss",
        "actor_name": "Alice",
        "language": "",
        "arena": "elites",
    }


class FakeMongoCollection:
    def __init__(self):
        self.indexes = []
        self.updates = []

    def create_index(self, fields, **kwargs):
        self.indexes.append((fields, kwargs))

    def update_one(self, query, update, *, upsert=False):
        self.updates.append((query, update, upsert))


class FakeMongoDatabase:
    def __init__(self, collection):
        self.collection = collection

    def __getitem__(self, name):
        assert name == "laclaugpt2_ai26_scraper_collection"
        return self.collection


class FakeMongoClient:
    collection = FakeMongoCollection()

    def __init__(self, uri, **kwargs):
        self.uri = uri
        self.kwargs = kwargs

    def __getitem__(self, name):
        assert name == "laclaugpt"
        return FakeMongoDatabase(self.collection)


def test_phase0_store_upserts_by_stable_document_id() -> None:
    FakeMongoClient.collection = FakeMongoCollection()
    store = Phase0MongoStore(
        "mongodb://example.invalid",
        "laclaugpt",
        "ai26",
        client_factory=FakeMongoClient,
    )
    record = NormalizedRecord(
        document_id="article-1",
        platform="rss",
        source_url="https://example.org/article",
        text="Article body",
        raw_payload={"id": "article-1"},
        collection_provenance=CollectionProvenance(module="rss-test"),
    )

    store.upsert(record)
    store.upsert(record)

    assert len(FakeMongoClient.collection.updates) == 2
    for query, update, upsert in FakeMongoClient.collection.updates:
        assert query == {"document_id": "article-1"}
        assert update["$set"]["source_url"] == "https://example.org/article"
        assert upsert is True
