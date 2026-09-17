from pathlib import Path

import pytest

from laclaugpt_data_collection.interchange import (
    from_cyborganthropology,
    from_flat_row,
    from_legacy_collection,
    from_mongo_document,
    migrate_payload,
    read_csv,
    read_jsonl,
    to_flat_row,
    to_mongo_document,
    write_csv,
    write_jsonl,
)
from laclaugpt_data_collection.models import (
    CanonicalRecord,
    CollectionProvenance,
    ContentSection,
    MediaReference,
    NormalizedRecord,
    SourceSection,
    canonicalize_source_url,
)
from laclaugpt_data_collection.storage.local import SQLiteRecordStore

SHARED_PARITY_FIXTURE = Path(__file__).parent / "fixtures" / "canonical_parity_v1.json"


def sample_record() -> CanonicalRecord:
    return CanonicalRecord(
        source_url="https://Example.Invalid/post/42/?utm_source=test#fragment",
        source_native_ids={"document_id": "42", "platform_id": "abc"},
        source=SourceSection(
            platform="synthetic",
            source_type="post",
            author="example",
            created_at="2026-09-15T12:00:00+03:00",
            collected_at="2026-09-15T09:05:00Z",
            collector="synthetic-collector",
            collection_method="api",
            language="en",
            raw_metadata={"engagement": {"likes": 2}},
            raw_ref="files/raw/synthetic.json",
        ),
        content=ContentSection(
            text="Synthetic source text",
            language="en",
            media_references=[
                MediaReference(
                    kind="image",
                    url="https://example.invalid/media/1.jpg",
                    object_ref="s3://example-bucket/media/1.jpg",
                    checksum="sha256:synthetic",
                )
            ],
        ),
        provenance=[
            CollectionProvenance(
                provenance_id="prov-1",
                collector="synthetic-collector",
                captured_at="2026-09-15T09:05:00Z",
                transformations=["synthetic-normalization"],
            )
        ],
    )


def assert_same(left: CanonicalRecord, right: CanonicalRecord) -> None:
    assert right.model_dump(mode="json") == left.model_dump(mode="json")
    assert right.source_url == left.source_url


def test_url_canonicalization_and_uri_identity() -> None:
    assert canonicalize_source_url(
        "HTTPS://Example.Invalid/post/42/?utm_source=x&ok=1#fragment"
    ) == "https://example.invalid/post/42?ok=1"
    assert canonicalize_source_url("at://did:plc:abc/app.bsky.feed.post/xyz") == (
        "at://did:plc:abc/app.bsky.feed.post/xyz"
    )


def test_flat_csv_jsonl_mongo_and_sqlite_round_trip(tmp_path: Path) -> None:
    record = sample_record()
    assert_same(record, from_flat_row(to_flat_row(record)))

    csv_path = tmp_path / "records.csv"
    write_csv(csv_path, [record])
    assert_same(record, read_csv(csv_path)[0])

    jsonl_path = tmp_path / "records.jsonl"
    write_jsonl(jsonl_path, [record])
    assert_same(record, read_jsonl(jsonl_path)[0])

    mongo = to_mongo_document(record)
    mongo["_id"] = "backend-only"
    assert_same(record, from_mongo_document(mongo))

    sqlite_path = tmp_path / "records.sqlite3"
    store = SQLiteRecordStore(sqlite_path)
    store.upsert(record)
    restored = store.get(record.source_url)
    assert restored is not None
    assert_same(record, restored)


def test_shared_cross_module_parity_fixture_round_trips(tmp_path: Path) -> None:
    import json

    payload = json.loads(SHARED_PARITY_FIXTURE.read_text(encoding="utf-8"))
    record = CanonicalRecord.model_validate(migrate_payload(payload))

    assert record.source_url == "https://example.invalid/laclaugpt/synthetic/record-001"
    assert record.source_native_ids["legacy_document_id"] == "legacy-001"
    assert record.source.raw_metadata["legacy_optional_field"] == "must-survive-roundtrip"
    assert record.content.transcripts[0]["text"] == "A synthetic transcript segment."
    assert record.content.ocr[0]["text"] == "SYNTHETIC ONLY"
    assert record.content.frames[0]["media_ref"].startswith("fixture://")
    assert record.content.media_references[0].media_type == "video"
    assert record.provenance[0].method == "synthetic_fixture"
    assert record.provenance[0].input_refs == []

    json_path = tmp_path / "record.json"
    json_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    from_json = CanonicalRecord.model_validate_json(json_path.read_text(encoding="utf-8"))
    assert_same(record, from_json)

    jsonl_path = tmp_path / "record.jsonl"
    write_jsonl(jsonl_path, [record])
    assert_same(record, read_jsonl(jsonl_path)[0])

    csv_path = tmp_path / "record.csv"
    write_csv(csv_path, [record])
    assert_same(record, read_csv(csv_path)[0])

    sqlite_path = tmp_path / "record.sqlite3"
    store = SQLiteRecordStore(sqlite_path)
    store.upsert(record)
    restored = store.get(record.source_url)
    assert restored is not None
    assert_same(record, restored)


def test_legacy_flat_normalized_record_becomes_canonical() -> None:
    record = from_legacy_collection(
        {
            "schema_version": "1.0",
            "document_id": "legacy-id",
            "platform": "synthetic",
            "author": "legacy-author",
            "timestamp": "2026-09-15T12:00:00Z",
            "source_url": "https://example.invalid/legacy/1",
            "text": "legacy text",
            "language": "en",
            "hashtags": ["example"],
            "engagement": {"likes": 1},
            "media_references": [],
            "raw_ref": "raw/example.json",
        }
    )
    assert record.source_url == "https://example.invalid/legacy/1"
    assert record.source_native_ids["document_id"] == "legacy-id"
    assert record.source.platform == "synthetic"
    assert record.content.text == "legacy text"
    assert "document_id" not in record.model_dump()


def test_cyborganthropology_fields_map_to_neutral_names() -> None:
    record = from_cyborganthropology(
        {
            "scraper_url": "https://example.invalid/article/1",
            "scraper_text": "Synthetic article",
            "scraper_type": "article",
            "scraper_date": "2026-09-14T10:00:00Z",
            "scraper_file": "files/raw/article.json",
            "scraper_json": {"synthetic": True},
            "source_type": "rss",
            "collector_id": "rss-agent",
            "scraped_at": "2026-09-15T09:00:00Z",
            "local_file": "files/media/example.jpg",
            "allas_file": "s3://example/media/example.jpg",
            "research_note": "private content is not copied",
        }
    )
    assert record.source.source_type == "article"
    assert record.source.collection_method == "rss"
    assert record.source.collector == "rss-agent"
    assert record.content.media_references[0].object_ref.startswith("s3://")
    assert record.legacy == {"research_note_present": True}


def test_text_only_record_needs_no_multimodal_fields() -> None:
    record = CanonicalRecord(
        source_url="file+sha256:synthetic",
        content=ContentSection(text="text only"),
    )
    assert record.content.media_references == []
    assert record.evidence == []
    assert record.analysis == {}


def test_compatibility_constructor_generates_stable_uri_fallback() -> None:
    record = NormalizedRecord(document_id="123", platform="rss", text="synthetic")
    assert record.source_url == "rss:123"
    assert record.document_id == "123"
    assert record.dedup_key == "rss:123"


def test_source_url_is_required_for_canonical_record() -> None:
    with pytest.raises(Exception):
        CanonicalRecord(source_url="")
