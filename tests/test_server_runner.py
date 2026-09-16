from pathlib import Path

from laclaugpt_data_collection.collectors.base import CollectionResult
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord
from laclaugpt_data_collection.realtime import parse_source_time
from laclaugpt_data_collection.server_runner import load_feed_manifest, run_distributed_rss


class FakeRedis:
    def __init__(self):
        self.leases = []

    def acquire_once(self, resource, *, ttl_seconds=3600):
        self.leases.append((resource, ttl_seconds))
        return True


class FakeSink:
    last = None

    def __init__(self, settings):
        self.settings = settings
        self.redis = FakeRedis()
        self.records = []
        FakeSink.last = self

    def assert_private_config(self, path):
        return Path(path)

    def ingest(self, record):
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
    run_id = "shared-run-001"


def test_manifest_loader_uses_feed_array(tmp_path: Path) -> None:
    path = tmp_path / "sources.toml"
    path.write_text(
        '[[feed]]\nname="one"\nfeed_url="https://example.org/feed"\npriority="P1"\n',
        encoding="utf-8",
    )
    assert load_feed_manifest(path) == [
        {"name": "one", "feed_url": "https://example.org/feed", "priority": "P1"}
    ]


def test_rfc_rss_timestamp_is_supported() -> None:
    parsed = parse_source_time("Wed, 16 Sep 2026 10:00:00 GMT")
    assert parsed is not None
    assert parsed.isoformat() == "2026-09-16T10:00:00+00:00"


def test_server_worker_filters_pre_floor_and_syncs_bounded_new_records(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = tmp_path / "sources.toml"
    manifest.write_text(
        '[[feed]]\nname="one"\nfeed_url="https://example.org/feed"\n'
        'source_family="synthetic"\npriority="P1"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("laclaugpt_data_collection.server_runner.DistributedCaptureSink", FakeSink)
    monkeypatch.setattr("laclaugpt_data_collection.server_runner.RSSCollector", FakeRSSCollector)

    result = run_distributed_rss(
        SettingsStub(),
        source_manifest=manifest,
        collection_id="ai26",
        max_feeds=1,
        per_feed_limit=2,
        limit=1,
    )
    assert result["records_collected"] == 2
    assert result["records_excluded"] == 1
    assert result["records_synced"] == 1
    assert FakeSink.last is not None
    stored = FakeSink.last.records[0]
    assert stored["collection_id"] == "ai26"
    assert stored["source"]["raw_metadata"]["source_name"] == "one"
    assert stored["provenance"][-1]["metadata"]["worker_id"] == "linux-server-rss"
    assert FakeSink.last.redis.leases[0][0].startswith("server-rss:shared-run-001:")
