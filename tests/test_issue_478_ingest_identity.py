"""Cross-machine ingestion identity for AI26 (#478).

Three localhost collectors are meant to feed one `ai26__records`. Before that is true in production, the
store's key has to be the *post*, not the string a browser happened to hold: `x.com/u/status/1`,
`twitter.com/U/status/1?s=20`, `mobile.x.com/u/status/1/` and `x.com/i/web/status/1` are one post, and a
second machine must not create a second document for it.

These tests are synthetic (this repository is public and carries no corpus), but they assert the behaviour
that the real store currently cannot exercise: it has one writer, so the multi-writer path has no history.
"""

from __future__ import annotations

import pytest

from laclaugpt_data_collection.models import (
    CanonicalRecord,
    canonicalize_source_url,
    source_identity,
)
from laclaugpt_data_collection.storage.mongodb import MongoRecordStore
from laclaugpt_data_collection.x_ingest_identity import audit_documents, backfill

POST_ID = "2100246033183699070"
VARIANTS = [
    f"https://x.com/Example_User/status/{POST_ID}",
    f"https://twitter.com/example_user/status/{POST_ID}?s=20&t=tracking",
    f"https://mobile.x.com/Example_User/status/{POST_ID}/",
    f"https://www.twitter.com/Example_User/status/{POST_ID}/photo/1",
    f"https://x.com/i/web/status/{POST_ID}",
]


class FakeCollection:
    """The handful of pymongo operations the store uses, with the semantics that matter for identity.

    Documents always carry an ``_id``, as they do in MongoDB: a fake that let documents exist without one
    would make an adoption test pass while the real update silently matched nothing.
    """

    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.indexes: list[dict] = []
        self.name = "ai26__records"

    def insert(self, document: dict) -> dict:
        stored = {"_id": len(self.documents), **document}
        self.documents.append(stored)
        return stored

    def create_index(self, keys, *, unique=False, name="", partialFilterExpression=None) -> None:
        self.indexes.append(
            {"keys": keys, "unique": unique, "name": name, "partial": partialFilterExpression}
        )

    @staticmethod
    def _matches(document, query) -> bool:
        import re

        for key, value in query.items():
            if isinstance(value, dict):
                if "$exists" in value:
                    if (key in document) != value["$exists"]:
                        return False
                elif "$regex" in value:
                    if not re.search(value["$regex"], str(document.get(key) or "")):
                        return False
                else:  # pragma: no cover - unsupported operator
                    raise AssertionError(f"unsupported query operator: {value}")
            elif document.get(key) != value:
                return False
        return True

    def find_one(self, query, projection=None):
        for document in self.documents:
            if self._matches(document, query):
                return dict(document)
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        for document in self.documents:
            if self._matches(document, query):
                yield dict(document)

    def replace_one(self, query, payload, upsert=False):
        for index, document in enumerate(self.documents):
            if self._matches(document, query):
                self.documents[index] = {"_id": document["_id"], **payload}
                return
        if upsert:
            self.insert(payload)

    def update_one(self, query, update):
        for index, document in enumerate(self.documents):
            if self._matches(document, query):
                self.documents[index] = {**document, **update.get("$set", {})}
                return


def record(url: str) -> CanonicalRecord:
    return CanonicalRecord(source_url=url, source={"platform": "x", "author": "example_user"})


def store(collection: FakeCollection) -> MongoRecordStore:
    class FakeDatabase:
        def __getitem__(self, name):
            return collection

    class FakeClient:
        def __getitem__(self, name):
            return FakeDatabase()

    return MongoRecordStore(
        uri="mongodb://example.invalid",
        database="db",
        collection="ai26__records",
        project_id="ai26",
        client_factory=lambda *args, **kwargs: FakeClient(),
    )


class TestCanonicalIdentity:
    @pytest.mark.parametrize("url", VARIANTS)
    def test_every_spelling_of_one_post_has_one_identity(self, url):
        assert source_identity(url) == f"https://x.com/i/status/{POST_ID}"

    def test_a_different_post_keeps_a_different_identity(self):
        other = "https://x.com/Example_User/status/2100246033183699999"
        assert source_identity(other) != source_identity(VARIANTS[0])

    def test_non_x_urls_keep_their_host(self):
        # Folding a news site's host would change what the source is, not how it is spelled.
        url = "https://www.example.org/article/?utm_source=x&id=7"
        # Non-X hosts are untouched apart from tracking removal and the trailing slash.
        assert canonicalize_source_url(url) == "https://www.example.org/article?id=7"
        assert source_identity(url) == "https://www.example.org/article?id=7"

    def test_the_record_url_keeps_the_screen_name_a_reader_can_open(self):
        # `source_url` is what a researcher sees; identity is what the store keys on.
        assert (
            canonicalize_source_url(VARIANTS[0]) == f"https://x.com/Example_User/status/{POST_ID}"
        )


class TestStoreKeying:
    def test_the_payload_carries_the_identity_and_keeps_the_captured_url(self):
        collection = FakeCollection()
        store(collection).upsert(record(VARIANTS[1]))
        stored = collection.documents[0]
        # The record keeps one canonical spelling; identity is what makes two machines agree on it.
        # The captured URL is preserved as evidence (only its host case is normalised); identity is derived.
        assert stored["source_url"] == VARIANTS[1]
        assert stored["source_identity"] == f"https://x.com/i/status/{POST_ID}"

    def test_two_machines_writing_two_spellings_produce_one_document(self):
        collection = FakeCollection()
        first = store(collection).upsert(record(VARIANTS[0]))
        second = store(collection).upsert(record(VARIANTS[1]))
        assert (first, second) == (True, False)
        assert len(collection.documents) == 1

    def test_a_legacy_document_is_adopted_not_duplicated(self):
        collection = FakeCollection()
        collection.insert(
            {
                "project_id": "ai26",
                "collection_id": "ai26",
                "source_url": VARIANTS[2],
                "content": {},
            }
        )
        store(collection).upsert(record(VARIANTS[0]))
        assert len(collection.documents) == 1
        assert collection.documents[0]["_id"] == 0
        assert collection.documents[0]["source_identity"] == f"https://x.com/i/status/{POST_ID}"

    def test_a_unique_identity_index_is_declared_partially(self):
        collection = FakeCollection()
        store(collection)
        identity_index = next(
            index for index in collection.indexes if index["name"] == "routing_identity_unique"
        )
        assert identity_index["unique"] is True
        # Partial, so documents written before the field existed keep loading until the backfill runs.
        assert identity_index["partial"] == {"source_identity": {"$type": "string"}}


class TestAudit:
    def test_an_audit_counts_duplicates_by_identity_and_prints_no_urls(self):
        report = audit_documents(
            [
                {"source_url": VARIANTS[0], "source_identity": f"https://x.com/i/status/{POST_ID}"},
                {"source_url": VARIANTS[1]},
                {"source_url": "https://example.org/a", "source_identity": "https://example.org/a"},
            ]
        )
        assert report["documents"] == 3
        assert report["distinct_identities"] == 2
        assert report["duplicate_identities"] == 1
        assert report["duplicate_documents"] == 1
        assert report["documents_without_identity"] == 1
        assert report["variant_counts"]["has_query"] == 1
        assert POST_ID not in str(report)  # counts only

    def test_a_single_writer_store_reads_as_clean(self):
        report = audit_documents([{"source_url": VARIANTS[0], "source_identity": "x"}])
        assert report["duplicate_documents"] == 0
        assert report["documents_without_identity"] == 0


class TestBackfill:
    def test_dry_run_counts_without_writing(self):
        collection = FakeCollection()
        collection.insert({"project_id": "ai26", "source_url": VARIANTS[0]})
        report = backfill(collection, "ai26", write=False)
        assert report == {
            "project_id": "ai26",
            "documents_missing_identity": 1,
            "documents_updated": 0,
            "applied": False,
            "note": "the captured URL is never modified; only the derived routing key is added",
        }
        assert "source_identity" not in collection.documents[0]

    def test_a_write_stamps_the_identity_and_leaves_the_url_alone(self):
        collection = FakeCollection()
        collection.insert({"project_id": "ai26", "source_url": VARIANTS[1]})
        report = backfill(collection, "ai26", write=True)
        assert report["documents_updated"] == 1
        assert collection.documents[0]["source_identity"] == f"https://x.com/i/status/{POST_ID}"

    def test_the_backfill_is_idempotent(self):
        collection = FakeCollection()
        collection.insert({"project_id": "ai26", "source_url": VARIANTS[1]})
        backfill(collection, "ai26", write=True)
        assert backfill(collection, "ai26", write=True)["documents_updated"] == 0
