"""Portable CSV storage for canonical Collection records.

Nested sections are encoded as deterministic JSON strings so CSV can round-trip
into MongoDB without losing graph references, vector metadata or analysis fields.
"""
from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..models import CanonicalRecord, canonicalize_source_url

CSV_FIELDS = [
    "schema_version",
    "source_url",
    "source_native_ids",
    "raw_capture",
    "source",
    "content",
    "intermediate",
    "relationships",
    "embeddings",
    "evidence",
    "analysis",
    "human_readable",
    "provenance",
    "review",
    "legacy",
]

_JSON_FIELDS = set(CSV_FIELDS) - {"schema_version", "source_url"}


def record_to_csv_row(record: CanonicalRecord) -> dict[str, str]:
    payload = record.model_dump(mode="json")
    return {
        field: (
            str(payload[field])
            if field in {"schema_version", "source_url"}
            else json.dumps(payload[field], ensure_ascii=False, sort_keys=True)
        )
        for field in CSV_FIELDS
    }


def csv_row_to_record(row: dict[str, str]) -> CanonicalRecord:
    payload: dict[str, Any] = {
        "schema_version": row.get("schema_version") or "1.1.0",
        "source_url": row["source_url"],
    }
    for field in _JSON_FIELDS:
        raw = row.get(field, "")
        if raw:
            payload[field] = json.loads(raw)
    return CanonicalRecord.model_validate(payload)


class CSVRecordStore:
    """Small, dependency-free record store keyed by canonical ``source_url``."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_all([])

    def _read_all(self) -> list[CanonicalRecord]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        with self.path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            return [csv_row_to_record(dict(row)) for row in reader]

    def _write_all(self, records: Iterable[CanonicalRecord]) -> None:
        with self.path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for record in sorted(records, key=lambda item: item.source_url):
                writer.writerow(record_to_csv_row(record))

    def upsert(self, record: CanonicalRecord) -> None:
        records = {item.source_url: item for item in self._read_all()}
        records[record.source_url] = record
        self._write_all(records.values())

    def upsert_many(self, records: Iterable[CanonicalRecord]) -> None:
        current = {item.source_url: item for item in self._read_all()}
        for record in records:
            current[record.source_url] = record
        self._write_all(current.values())

    def contains(self, source_url: str) -> bool:
        identity = canonicalize_source_url(source_url)
        return any(record.source_url == identity for record in self._read_all())

    def get(self, source_url: str) -> CanonicalRecord | None:
        identity = canonicalize_source_url(source_url)
        return next((record for record in self._read_all() if record.source_url == identity), None)

    def all(self) -> list[CanonicalRecord]:
        return self._read_all()
