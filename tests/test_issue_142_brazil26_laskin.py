from __future__ import annotations

from pathlib import Path

from laclaugpt_data_collection.distributed import ProjectNamespace
from laclaugpt_data_collection.storage.remote import MongoRecordStore

ROOT = Path(__file__).resolve().parents[1]


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
        self.last_query = None
        self.last_cursor = None

    def find(self, query):
        self.last_query = query
        self.last_cursor = FakeCursor(self.documents)
        return self.last_cursor


def test_brazil26_laskin_profile_is_non_browser_only() -> None:
    profile = (ROOT / "configs" / "brazil26.laskin-remote.example.toml").read_text(
        encoding="utf-8"
    )

    assert 'profile = "brazil26-laskin-remote"' in profile
    assert 'project_id = "brazil26"' in profile
    assert 'browser = "none"' in profile
    assert 'execution = "cron"' in profile
    assert 'non_browser_enabled = true' in profile
    assert 'collection_id = "brazil26"' in profile
    assert "firefox" not in profile.casefold()


def test_brazil26_laskin_wrappers_enforce_study_and_browser_boundaries() -> None:
    collect = (ROOT / "scripts" / "run_brazil26_laskin_collect.sh").read_text(
        encoding="utf-8"
    )
    media = (ROOT / "scripts" / "run_brazil26_laskin_media.sh").read_text(
        encoding="utf-8"
    )

    for text in (collect, media):
        assert '!= "brazil26"' in text
        assert "LACLAUGPT_BROWSER" in text
        assert "browser collection is localhost-only" in text
        assert "flock -n 9" in text
        assert 'export LACLAUGPT_PROJECT_ID=brazil26' in text
        assert ".venv/bin/" in text
        assert "python3 -m laclaugpt_data_collection." in text

    assert "--study-config" in collect
    assert "--source-manifest" in collect
    assert "--collection-id brazil26" in collect
    assert "laclaugpt-distributed-media" in media


def test_brazil26_pending_media_is_discovered_from_shared_mongodb() -> None:
    store = object.__new__(MongoRecordStore)
    store.project_id = "brazil26"
    store._collection = FakeMongoCollection(
        [
            {
                "_id": "localhost-browser-object",
                "project_id": "brazil26",
                "collection_id": "brazil26",
                "source_url": "https://example.org/browser-capture",
                "content": {
                    "media_references": [
                        {"url": "https://cdn.example.org/image.jpg", "kind": "image"}
                    ]
                },
            }
        ]
    )

    records = store.pending_media_records(collection_id="brazil26", limit=10)

    assert records[0]["collection_id"] == "brazil26"
    assert records[0]["source_url"] == "https://example.org/browser-capture"
    assert store._collection.last_query["project_id"] == "brazil26"
    assert store._collection.last_query["collection_id"] == "brazil26"
    assert store._collection.last_cursor.limit_value == 10


def test_ai26_and_brazil26_remote_namespaces_are_isolated() -> None:
    ai26 = ProjectNamespace("ai26")
    brazil26 = ProjectNamespace("brazil26")

    assert ai26.mongo_collection("records") != brazil26.mongo_collection("records")
    assert ai26.redis_base != brazil26.redis_base
    assert ai26.s3_key("media", "same") != brazil26.s3_key("media", "same")
    assert brazil26.mongo_collection("records") == "brazil26__records"
    assert brazil26.redis_base == "laclaugpt:brazil26"
    assert brazil26.s3_key("media").startswith("projects/brazil26/")
