from typing import Any

from laclaugpt_data_collection.models import CanonicalRecord, CollectionProvenance
from laclaugpt_data_collection.storage.mongodb import MongoRecordStore


class FakeCollection:
    name = "records"

    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []

    def create_index(self, *args: Any, **kwargs: Any) -> str:
        return str(kwargs.get("name", "index"))

    def replace_one(self, query: dict[str, Any], payload: dict[str, Any], *, upsert: bool) -> None:
        assert upsert
        self.documents = [
            doc for doc in self.documents
            if not all(doc.get(key) == value for key, value in query.items())
        ]
        self.documents.append(payload)

    def find_one(self, query: dict[str, Any], projection: dict[str, int]) -> dict[str, int] | None:
        del projection
        for doc in self.documents:
            if all(doc.get(key) == value for key, value in query.items()):
                return {"_id": 1}
        return None


class FakeDatabase:
    def __init__(self) -> None:
        self.collection = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "records"
        return self.collection


class FakeClient:
    instances = 0

    def __init__(self, uri: str, **kwargs: Any) -> None:
        assert uri == "mongodb://synthetic"
        assert kwargs["serverSelectionTimeoutMS"] == 50
        type(self).instances += 1
        self.database = FakeDatabase()

    def __getitem__(self, name: str) -> FakeDatabase:
        assert name == "laclaugpt"
        return self.database


def test_phase1_mongo_only_upsert_is_idempotent_and_nested() -> None:
    FakeClient.instances = 0
    store = MongoRecordStore(
        "mongodb://synthetic",
        "laclaugpt",
        "records",
        "SYNTH26",
        connect_timeout_ms=50,
        client_factory=FakeClient,
    )
    record = CanonicalRecord(
        source_url="https://EXAMPLE.invalid/post/7/?utm_source=phase1",
        source_native_ids={"platform_post_id": "post-7"},
        source={
            "platform": "synthetic",
            "source_type": "api",
            "raw_metadata": {"collection_id": "SYNTH26", "nested": {"kept": True}},
        },
        content={
            "text": "Mongo-only Phase 1 fixture",
            "media_references": [{"kind": "image", "ref": "fixture://image/7"}],
        },
        raw_capture={"payload": {"id": "post-7", "nested": {"raw": True}}},
        provenance=[
            CollectionProvenance(
                run_id="run-7",
                module="collection-plugin:synthetic",
                metadata={"collection_id": "SYNTH26"},
            )
        ],
    )

    store.upsert(record)
    store.upsert(record)

    assert FakeClient.instances == 1
    assert len(store._collection.documents) == 1
    document = store._collection.documents[0]
    assert document["source_url"] == "https://example.invalid/post/7"
    assert document["source"]["raw_metadata"]["nested"] == {"kept": True}
    assert document["raw_capture"]["payload"]["nested"] == {"raw": True}
    assert document["content"]["media_references"][0]["ref"] == "fixture://image/7"
    assert document["handoff"]["status"] == "ready"
    rebuilt = store.from_document(document)
    assert rebuilt.model_dump(mode="json") == record.model_dump(mode="json")
