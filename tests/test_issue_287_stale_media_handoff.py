"""Regression tests for issue #287: resolved media with stale handoff envelopes."""
from __future__ import annotations

from types import SimpleNamespace

from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.storage.remote import MongoRecordStore


def record(*, ready=True):
    refs = [{"url": "https://example.org/document.pdf", "media_index": 0}]
    if ready:
        refs[0]["object_ref"] = "s3://bucket/media/document.pdf"
        refs[0]["checksum"] = "abc123"
    return {
        "_id": "record-1",
        "project_id": "ai26",
        "collection_id": "ai26",
        "source_url": "https://arxiv.org/abs/2610.20606v1",
        "source": {
            "platform": "arxiv",
            "source_type": "article",
            "created_at": "2026-10-15T10:00:00Z",
        },
        "content": {"text": "AI research", "media_references": refs},
        "provenance": [{"run_id": "ai26-distributed-001", "metadata": {"collection_id": "ai26"}}],
    }


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents
        self.updates = []
        self.last_query = None

    def find(self, query):
        self.last_query = query
        return FakeCursor(self.documents)

    def update_one(self, query, update):
        self.updates.append((query, update))
        doc = next((d for d in self.documents if d["_id"] == query["_id"]), None)
        if doc is None or doc["handoff"]["status"] != query["handoff.status"] or (
            doc["handoff"].get("handoff_key") != query["handoff.handoff_key"]
        ):
            return SimpleNamespace(modified_count=0)
        doc["handoff"] = update["$set"]["handoff"]
        return SimpleNamespace(modified_count=1)


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def limit(self, limit):
        return self.documents[:limit]


def store_for(documents):
    store = MongoRecordStore.__new__(MongoRecordStore)
    store.project_id = "ai26"
    store._collection = FakeCollection(documents)
    return store


def test_completed_object_reconciles_without_changing_media_payload():
    doc = record()
    assert build_handoff(doc, project_id="ai26")["status"] == "ready"
    doc["handoff"] = {**build_handoff(record(ready=False), project_id="ai26"),
                      "run_id": "ai26-distributed-001"}
    store = store_for([doc])
    original = dict(doc["content"]["media_references"][0])

    assert store.reconcile_waiting_media(collection_id="ai26") == 1
    assert doc["handoff"]["status"] == "ready"
    assert doc["handoff"]["reason"] == "media_ready"
    assert doc["handoff"]["run_id"] == "ai26-distributed-001"
    assert doc["content"]["media_references"][0] == original
    assert store.reconcile_waiting_media(collection_id="ai26") == 0
    assert store._collection.last_query["collection_id"] == "ai26"


def test_partially_unresolved_media_is_not_promoted():
    doc = record()
    doc["content"]["media_references"].append({
        "url": "https://example.org/missing.pdf",
        "media_index": 1,
        "object_ref": "",
    })
    doc["handoff"] = build_handoff(doc, project_id="ai26")
    store = store_for([doc])

    assert store.reconcile_waiting_media(collection_id="ai26") == 0
    assert doc["handoff"]["status"] == "waiting_media"
    assert store._collection.updates == []


def test_reconciliation_is_bounded_and_rejects_invalid_limit():
    docs = [record(), record()]
    docs[1]["_id"] = "record-2"
    for d in docs:
        d["handoff"] = build_handoff(record(ready=False), project_id="ai26")
    store = store_for(docs)
    assert store.reconcile_waiting_media(limit=1) == 1
    import pytest
    with pytest.raises(ValueError):
        store.reconcile_waiting_media(limit=0)
