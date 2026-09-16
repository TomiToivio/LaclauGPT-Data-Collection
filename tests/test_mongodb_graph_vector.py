from __future__ import annotations

from typing import Any

from laclaugpt_data_collection.models import CanonicalRecord
from laclaugpt_data_collection.storage.mongodb import MongoRecordStore


class FakeAdmin:
    def command(self, name: str) -> dict[str, int]:
        assert name == "ping"
        return {"ok": 1}


class FakeCollection:
    name = "records"

    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.last_pipeline: list[dict[str, Any]] | None = None

    def create_index(self, *args: Any, **kwargs: Any) -> str:
        return str(kwargs.get("name", "index"))

    def replace_one(self, query: dict[str, Any], payload: dict[str, Any], *, upsert: bool) -> None:
        assert upsert
        self.documents = [doc for doc in self.documents if not all(doc.get(k) == v for k, v in query.items())]
        self.documents.append(payload)

    def find_one(self, query: dict[str, Any], projection: dict[str, int]) -> dict[str, int] | None:
        del projection
        return {"_id": 1} if any(all(doc.get(k) == v for k, v in query.items()) for doc in self.documents) else None

    def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.last_pipeline = pipeline
        return [{"related_records": []}]


class FakeDatabase:
    def __init__(self) -> None:
        self.collection = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "records"
        return self.collection

    def command(self, name: str) -> dict[str, str]:
        assert name == "buildInfo"
        return {"version": "8.0-test"}


class FakeClient:
    def __init__(self, uri: str, **kwargs: Any) -> None:
        assert uri.startswith("mongodb://")
        assert kwargs["serverSelectionTimeoutMS"] == 123
        self.admin = FakeAdmin()
        self.database = FakeDatabase()

    def __getitem__(self, name: str) -> FakeDatabase:
        assert name == "laclaugpt"
        return self.database


def test_mongodb_roundtrip_preserves_graph_and_vector_enrichment() -> None:
    store = MongoRecordStore(
        "mongodb://synthetic",
        "laclaugpt",
        "records",
        "AI26",
        connect_timeout_ms=123,
        graph_max_depth=4,
        client_factory=FakeClient,
    )
    record = CanonicalRecord(
        source_url="https://example.org/a",
        analysis={
            "relationships": {"targets": ["https://example.org/b"]},
            "embeddings": [{"vector": [0.25, 0.75], "model": "synthetic", "version": "1"}],
        },
    )
    store.upsert(record)
    document = store._collection.documents[0]
    rebuilt = store.from_document(document)
    assert rebuilt.analysis == record.analysis
    assert store.ping()
    assert store.capabilities()["graph_lookup"] is True
    assert store.capabilities()["vector_search"] is False


def test_graph_lookup_is_bounded() -> None:
    store = MongoRecordStore(
        "mongodb://synthetic",
        "laclaugpt",
        "records",
        "AI26",
        connect_timeout_ms=123,
        graph_max_depth=2,
        client_factory=FakeClient,
    )
    result = store.graph_lookup("https://example.org/a", max_depth=99)
    assert result == [{"related_records": []}]
    pipeline = store._collection.last_pipeline
    assert pipeline is not None
    graph_stage = pipeline[1]["$graphLookup"]
    assert graph_stage["maxDepth"] == 2
    assert graph_stage["connectToField"] == "source_url"
