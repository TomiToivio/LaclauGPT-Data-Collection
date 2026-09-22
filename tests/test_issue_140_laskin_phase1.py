from __future__ import annotations

from pathlib import Path

from laclaugpt_data_collection.collectors.base import CollectionResult
from laclaugpt_data_collection.distributed import ProjectNamespace
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord
from laclaugpt_data_collection.ai26_laskin_runner import _records_for_job
from laclaugpt_data_collection.server_runner import load_feed_manifest, run_phase1_rss
from laclaugpt_data_collection.storage.remote import MongoRecordStore


class FakeCursor:
    def __init__(self, documents):
        self.documents = list(documents)
        self.limit_value = None

    def limit(self, value):
        self.limit_value = value
        return iter(self.documents[:value])


class FakeMongoCollection:
    def __init__(self, documents=None):
        self.documents = list(documents or [])
        self.indexes = []
        self.last_query = None
        self.last_cursor = None

    def create_index(self, fields, **kwargs):
        self.indexes.append((fields, kwargs))

    def find(self, query):
        self.last_query = query
        self.last_cursor = FakeCursor(self.documents)
        return self.last_cursor


def test_pending_media_records_are_discovered_from_shared_mongodb() -> None:
    store = object.__new__(MongoRecordStore)
    store.project_id = "ai26"
    store._collection = FakeMongoCollection(
        [
            {
                "_id": "mongo-id",
                "project_id": "ai26",
                "collection_id": "ai26",
                "source_url": "https://example.org/browser-only",
                "content": {
                    "media_references": [
                        {"url": "https://cdn.example.org/image.jpg", "kind": "image"}
                    ]
                },
                "handoff": {"status": "ready"},
            }
        ]
    )

    records = store.pending_media_records(collection_id="ai26", limit=25)

    assert records == [
        {
            "project_id": "ai26",
            "collection_id": "ai26",
            "source_url": "https://example.org/browser-only",
            "content": {
                "media_references": [
                    {"url": "https://cdn.example.org/image.jpg", "kind": "image"}
                ]
            },
        }
    ]
    query = store._collection.last_query
    assert query["project_id"] == "ai26"
    assert query["collection_id"] == "ai26"
    assert "content.media_references" in query
    assert store._collection.last_cursor.limit_value == 25


class FakeRSSCollector:
    def __init__(self, feed_urls, *, max_items_per_feed=100):
        self.feed_url = feed_urls[0]
        self.max_items_per_feed = max_items_per_feed

    def collect(self):
        return CollectionResult(
            records=[
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
        )


class SettingsStub:
    project_id = "ai26"
    distributed_namespace = ProjectNamespace("ai26")


class FakeSink:
    last = None

    def __init__(self, settings):
        self.settings = settings
        self.records = []
        self.notification_errors = []
        self.checked_config = None
        FakeSink.last = self

    def assert_private_config(self, study_config):
        self.checked_config = Path(study_config)
        return self.checked_config

    def ingest(self, payload):
        self.records.append(payload)


def test_phase1_laskin_rss_uses_canonical_sink_and_date_floor(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = tmp_path / "sources.toml"
    manifest.write_text(
        '[[feed]]\nname="one"\nfeed_url="https://example.org/feed"\n'
        'source_family="synthetic"\narena="elites"\npriority="P1"\n',
        encoding="utf-8",
    )
    study = tmp_path / "ai26.yaml"
    study.write_text("study: ai26\n", encoding="utf-8")

    monkeypatch.setattr(
        "laclaugpt_data_collection.server_runner.RSSCollector",
        FakeRSSCollector,
    )
    monkeypatch.setattr(
        "laclaugpt_data_collection.distributed_capture.DistributedCaptureSink",
        FakeSink,
    )

    summary = run_phase1_rss(
        SettingsStub(),
        study_config=study,
        source_manifest=manifest,
        collection_id="ai26",
        max_feeds=1,
        per_feed_limit=2,
        limit=10,
        rotation=0,
    )

    assert summary["records_collected"] == 2
    assert summary["records_synced"] == 1
    assert summary["skipped_before_publication_floor"] == 1
    assert summary["mongodb_collection"] == "ai26__records"
    assert FakeSink.last is not None
    assert FakeSink.last.checked_config == study

    stored = FakeSink.last.records
    assert len(stored) == 1
    assert stored[0]["collection_id"] == "ai26"
    assert stored[0]["arena"] == "elites"
    assert stored[0]["source_url"].endswith("/new")
    assert stored[0]["provenance"][-1]["metadata"]["worker_id"] == "linux-server-rss"


def test_issue_170_openai_news_uses_official_rss_feed_not_blocked_html() -> None:
    manifest = Path(__file__).resolve().parents[1] / "configs" / "studies" / "ai26.sources.example.toml"
    feeds = load_feed_manifest(manifest)
    openai = [row for row in feeds if row.get("name") == "openai_news"]

    assert len(openai) == 1
    assert openai[0]["feed_url"] == "https://openai.com/news/rss.xml"
    assert openai[0]["homepage"] == "https://openai.com/news/"
    assert openai[0]["priority"] == "P1"

    text = manifest.read_text(encoding="utf-8")
    web_section = text.split("# Public web endpoints", 1)[1]
    assert '[[web_source]]\nname = "openai_news"' not in web_section


def test_issue_170_legacy_web_source_uses_fake_rss_fallback(monkeypatch) -> None:
    seen = {}

    class OneItemRSSCollector:
        def __init__(self, feed_urls, *, max_items_per_feed=100):
            seen["feed_urls"] = list(feed_urls)
            seen["max_items_per_feed"] = max_items_per_feed

        def collect(self):
            return CollectionResult(
                records=[
                    NormalizedRecord(
                        document_id="openai-item",
                        platform="rss",
                        timestamp="Wed, 16 Sep 2026 10:00:00 GMT",
                        source_url="https://openai.com/index/example",
                        text="OpenAI news item",
                        raw_payload={"id": "openai-item"},
                        collection_provenance=CollectionProvenance(module="issue-170-test"),
                    )
                ]
            )

    monkeypatch.setattr(
        "laclaugpt_data_collection.ai26_laskin_runner.RSSCollector",
        OneItemRSSCollector,
    )

    records, warnings = _records_for_job(
        {
            "kind": "web_source",
            "name": "openai_news",
            "homepage": "https://openai.com/news/",
            "arena": "elites",
            "priority": "P1",
            "source_family": "frontier lab",
        },
        collection_id="ai26",
        worker_id="laskin-test",
        per_source_limit=3,
    )

    assert seen["feed_urls"] == ["https://openai.com/news/rss.xml"]
    assert seen["max_items_per_feed"] == 3
    assert warnings == []
    assert len(records) == 1
    assert records[0].source.raw_metadata["source_name"] == "openai_news"
    assert records[0].source.raw_metadata["arena"] == "elites"
