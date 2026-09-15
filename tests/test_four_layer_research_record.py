import csv
import json
from pathlib import Path

from laclaugpt_data_collection.interchange import (
    from_mongo_document,
    read_csv,
    to_mongo_document,
    write_csv,
)
from laclaugpt_data_collection.normalize import normalise


def _record():
    raw_item = {"id": "1", "body": "Raw source body", "extra": {"native": True}}
    return normalise(
        "x",
        {
            "id": "1",
            "link": "https://example.invalid/post/1",
            "author": "synthetic",
            "body": "Normalized source body",
            "language_guess": "en",
        },
        raw_ref="raw/x/capture.ndjson",
        raw_payload=raw_item,
        metadata={"captured_at": "2026-09-16T00:00:00Z"},
    )


def test_csv_contains_nested_layers_and_legacy_research_columns(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    record = _record()
    write_csv(path, [record])

    with path.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert json.loads(row["raw_capture"])["payload"]["extra"]["native"] is True
    assert json.loads(row["intermediate"])["asr"] == []
    assert row["raw_ref"] == "raw/x/capture.ndjson"
    assert json.loads(row["raw_payload_json"])["body"] == "Raw source body"
    assert row["whisper_transcript"] == ""
    assert row["frame_1"] == ""
    assert row["summary_analysis"] == ""
    assert row["human_readable_summary"] == "Normalized source body"

    restored = read_csv(path)[0]
    assert restored.raw_capture.payload == record.raw_capture.payload
    assert restored.source_url == record.source_url


def test_mongo_document_keeps_all_layers() -> None:
    record = _record()
    document = to_mongo_document(record)
    assert document["raw_capture"]["payload"]["id"] == "1"
    assert "intermediate" in document
    assert "analysis" in document
    assert "human_readable" in document
    assert from_mongo_document(document).raw_capture.ref == "raw/x/capture.ndjson"
