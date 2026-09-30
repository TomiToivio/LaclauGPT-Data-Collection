"""Regression coverage for Parquet export of real canonical records (issue #196).

The existing Parquet test asserted only that a file appeared on disk when pyarrow
was importable, and named itself after the *missing*-dependency branch. It
therefore passed while Parquet export was broken for every real record.

The defect: ``CanonicalRecord.model_dump()`` yields empty sections (``analysis``,
``review``, ``legacy``, and often ``raw_metadata``/``stage_outputs``). PyArrow maps
a JSON ``{}`` to a struct with no child fields, and Parquet refuses to write such a
struct::

    ArrowNotImplementedError: Cannot write struct type 'analysis' with no child
    field to Parquet. Consider adding a dummy child field.

A freshly collected record always has these empty sections, so this is the normal
case. These tests assert the exported table is readable and faithful, which is the
guarantee the old test claimed to provide.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from laclaugpt_data_collection.integrations.interoperability import (
    import_4cat_record,
    write_records,
)

pyarrow = pytest.importorskip("pyarrow", reason="Parquet export needs the interop extra")
import pyarrow.parquet as pq  # noqa: E402  (after importorskip)


def _record():
    """A realistic record: several canonical sections are still empty at collection."""
    return import_4cat_record(
        {
            "id": "p-196",
            "platform": "telegram",
            "url": "https://example.test/post/196?utm_source=fixture",
            "author": "tutkija",
            "timestamp": "2026-09-17T08:00:00Z",
            "language": "fi",
            "text": "tekoälyä ja demokratiaa — żółw 🐢",
            "media": [{"type": "image", "url": "https://example.test/image.jpg"}],
            "sampling": {"query": "tekoäly", "mode": "search"},
        }
    )


def _empty_sections(record) -> list[str]:
    return [
        key
        for key, value in record.model_dump(mode="json").items()
        if isinstance(value, dict) and not value
    ]


def test_fresh_record_has_empty_sections_that_used_to_break_parquet() -> None:
    """Pin the precondition, so the reason for the fix stays visible.

    If a future change makes every section non-empty, this test fails and the
    normalisation in ``_parquet_safe`` can be reconsidered deliberately.
    """
    assert _empty_sections(_record()), "expected some canonical sections to be empty on a fresh record"


def test_parquet_export_of_a_real_record_round_trips(tmp_path: Path) -> None:
    """The actual guarantee: a real record exports to a readable Parquet table."""
    record = _record()
    path = tmp_path / "records.parquet"

    write_records([record], path)

    table = pq.read_table(path)
    assert table.num_rows == 1
    row = table.to_pylist()[0]

    # No field may be dropped: the Parquet reader still sees the full schema.
    assert sorted(row) == sorted(record.model_dump(mode="json"))
    # And the values must survive.
    assert row["source_url"] == "https://example.test/post/196"
    assert row["content"]["text"].endswith("🐢")
    assert row["content"]["media_references"][0]["kind"] == "image"
    assert row["raw_capture"]["payload"]["sampling"] == {
        "query": "tekoäly",
        "mode": "search",
    }


def test_parquet_export_of_a_minimal_record_round_trips(tmp_path: Path) -> None:
    """A record with nothing but an id and text is the smallest broken case."""
    path = tmp_path / "minimal.parquet"

    write_records([import_4cat_record({"id": "p-3", "text": "hello"})], path)

    table = pq.read_table(path)
    assert table.num_rows == 1
    assert table.to_pylist()[0]["content"]["text"] == "hello"


def test_parquet_export_of_several_records_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "many.parquet"

    write_records([_record(), import_4cat_record({"id": "p-4", "text": "second"})], path)

    table = pq.read_table(path)
    assert table.num_rows == 2
    assert [row["content"]["text"] for row in table.to_pylist()]


def test_empty_sections_become_null_in_parquet_only(tmp_path: Path) -> None:
    """Empty mappings become a Parquet null, and the other formats keep ``{}``.

    Null is the honest representation for "no value recorded", and normalising only
    in the Parquet branch keeps the canonical JSON/JSONL shapes unchanged.
    """
    record = _record()
    parquet_path = tmp_path / "r.parquet"
    json_path = tmp_path / "r.json"

    write_records([record], parquet_path)
    write_records([record], json_path)

    row = pq.read_table(parquet_path).to_pylist()[0]
    for section in _empty_sections(record):
        assert row[section] is None, f"{section} should be null in Parquet"

    payload = json.loads(json_path.read_text(encoding="utf-8"))[0]
    for section in _empty_sections(record):
        assert payload[section] == {}, f"{section} must stay {{}} in JSON"
