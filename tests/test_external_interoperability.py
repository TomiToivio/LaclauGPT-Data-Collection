from __future__ import annotations

import json

import pytest

from laclaugpt_data_collection.integrations.interoperability import (
    export_4cat_projection,
    import_4cat_record,
    import_dats_document,
    import_zeeschuimer_record,
    read_external_records,
    write_records,
)


def test_4cat_import_preserves_identity_unicode_media_and_provenance(tmp_path) -> None:
    row = {
        "id": "p-1",
        "platform": "telegram",
        "url": "https://example.test/post/1?utm_source=fixture",
        "author": "tutkija",
        "timestamp": "2026-09-17T08:00:00Z",
        "collected_at": "2026-09-17T08:05:00Z",
        "language": "fi",
        "text": "tekoälyä ja demokratiaa — żółw 🐢",
        "media": [{"type": "image", "url": "https://example.test/image.jpg"}],
        "sampling": {"query": "tekoäly", "mode": "search"},
    }

    record = import_4cat_record(row)

    assert record.source_url == "https://example.test/post/1"
    assert record.source_native_ids["4cat_id"] == "p-1"
    assert record.source.created_at == "2026-09-17T08:00:00+00:00"
    assert record.source.collected_at == "2026-09-17T08:05:00+00:00"
    assert record.content.text.endswith("🐢")
    assert record.content.media_references[0].kind == "image"
    assert record.raw_capture.payload == row
    assert record.provenance[0].metadata["external_tool"] == "4cat"
    assert record.provenance[0].metadata["sampling"]["query"] == "tekoäly"

    projection = export_4cat_projection(record)
    assert projection["id"] == "p-1"
    assert projection["text"] == row["text"]
    assert projection["laclaugpt_schema_version"] == record.schema_version

    output = tmp_path / "fourcat.jsonl"
    write_records([record], output, projection="4cat")
    loaded = json.loads(output.read_text(encoding="utf-8").strip())
    assert loaded["url"] == record.source_url


def test_4cat_requires_stable_identity() -> None:
    with pytest.raises(ValueError, match="URL or stable external ID"):
        import_4cat_record({"text": "orphan"})


def test_zeeschuimer_import_keeps_capture_time_distinct_from_source_time() -> None:
    payload = {
        "platform": "x",
        "timestamp_collected": 1_789_632_600_000,
        "query": "AGI",
        "data": {
            "rest_id": "123",
            "url": "https://example.test/x/123",
            "created_at": "2026-09-17T07:00:00Z",
            "username": "example",
            "text": "captured post",
        },
    }

    record = import_zeeschuimer_record(payload)

    assert record.source_native_ids["zeeschuimer_id"] == "123"
    assert record.source.created_at == "2026-09-17T07:00:00+00:00"
    assert record.source.collected_at != record.source.created_at
    assert record.provenance[0].metadata["sampling"]["query"] == "AGI"
    assert record.raw_capture.metadata["external_tool"] == "zeeschuimer"


def test_dats_document_import_preserves_project_and_document_ids() -> None:
    document = {
        "id": "doc-7",
        "project_id": "project-2",
        "title": "Interview note",
        "text": "Monikielinen dokumentti",
        "language": "fi",
        "file": "documents/doc-7.txt",
        "metadata": {"author": "Researcher", "type": "text"},
    }

    record = import_dats_document(document)

    assert record.source_url == "dats:project-2:doc-7"
    assert record.source_native_ids == {
        "dats_document_id": "doc-7",
        "dats_project_id": "project-2",
    }
    assert record.content.file_references == ["documents/doc-7.txt"]
    assert record.raw_capture.metadata["codes_and_annotations_imported"] is False
    assert record.source.raw_metadata["dats_metadata"]["author"] == "Researcher"


def test_read_external_records_supports_ndjson_and_deduplicates_by_canonical_url(tmp_path) -> None:
    source = tmp_path / "capture.ndjson"
    source.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "1",
                        "url": "https://example.test/a?utm_campaign=x",
                        "text": "first",
                    }
                ),
                json.dumps(
                    {
                        "id": "2",
                        "url": "https://example.test/a",
                        "text": "second",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    records = read_external_records(source, tool="4cat")

    assert len(records) == 2
    assert records[0].dedup_key == records[1].dedup_key


def test_write_canonical_csv_serializes_nested_fields(tmp_path) -> None:
    record = import_4cat_record(
        {"id": "p-2", "platform": "forum", "text": "hello", "author": "x"}
    )
    path = tmp_path / "records.csv"

    write_records([record], path)

    content = path.read_text(encoding="utf-8")
    assert "source_native_ids" in content
    assert "4cat_id" in content


def test_parquet_error_is_actionable_without_optional_dependency(tmp_path, monkeypatch) -> None:
    record = import_4cat_record({"id": "p-3", "text": "hello"})

    # The environment may or may not have pyarrow. This test only verifies successful
    # export when present; absence is covered by the explicit RuntimeError branch.
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="optional 'interop' dependency"):
            write_records([record], tmp_path / "records.parquet")
    else:
        write_records([record], tmp_path / "records.parquet")
        assert (tmp_path / "records.parquet").exists()
