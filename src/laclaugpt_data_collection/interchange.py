"""Canonical record serialization and bounded legacy adapters."""
from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .models import (
    SCHEMA_VERSION,
    CanonicalRecord,
    CollectionProvenance,
    ContentSection,
    MediaReference,
    NormalizedRecord,
    SourceSection,
)

NESTED_FIELDS = (
    "source_native_ids",
    "source",
    "content",
    "evidence",
    "analysis",
    "provenance",
    "review",
    "legacy",
)


def to_flat_row(record: CanonicalRecord) -> dict[str, str]:
    payload = record.model_dump(mode="json")
    return {
        "schema_version": record.schema_version,
        "source_url": record.source_url,
        **{
            key: json.dumps(payload[key], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for key in NESTED_FIELDS
        },
    }


def from_flat_row(row: Mapping[str, Any]) -> CanonicalRecord:
    payload: dict[str, Any] = {
        "schema_version": _scalar(row.get("schema_version")) or SCHEMA_VERSION,
        "source_url": _scalar(row.get("source_url")),
    }
    for key in NESTED_FIELDS:
        default: Any = [] if key in {"evidence", "provenance"} else {}
        payload[key] = _json_cell(row.get(key), default)
    return CanonicalRecord.model_validate(migrate_payload(payload))


def write_csv(path: str | Path, records: Iterable[CanonicalRecord]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["schema_version", "source_url", *NESTED_FIELDS])
        writer.writeheader()
        for record in records:
            writer.writerow(to_flat_row(record))


def read_csv(path: str | Path) -> list[CanonicalRecord]:
    source = Path(path)
    if not source.exists():
        return []
    with source.open("r", encoding="utf-8", newline="") as handle:
        return [from_flat_row(row) for row in csv.DictReader(handle)]


def write_jsonl(path: str | Path, records: Iterable[CanonicalRecord]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json())
            handle.write("\n")


def read_jsonl(path: str | Path) -> list[CanonicalRecord]:
    source = Path(path)
    if not source.exists():
        return []
    records: list[CanonicalRecord] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(CanonicalRecord.model_validate(migrate_payload(json.loads(line))))
    return records


def to_mongo_document(record: CanonicalRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


def from_mongo_document(document: Mapping[str, Any]) -> CanonicalRecord:
    return CanonicalRecord.model_validate(
        migrate_payload({key: value for key, value in document.items() if key != "_id"})
    )


def from_cyborganthropology(record: Mapping[str, Any]) -> CanonicalRecord:
    """Adapt the public CyborgAnthropology ScrapedItem vocabulary."""
    media: list[MediaReference] = []
    if record.get("local_file") or record.get("allas_file"):
        media.append(
            MediaReference(
                kind="file",
                local_ref=_scalar(record.get("local_file")),
                object_ref=_scalar(record.get("allas_file")),
            )
        )
    captured = _scalar(record.get("scraped_at"))
    provenance = CollectionProvenance(
        collector=_scalar(record.get("collector_id")) or "legacy-collector",
        captured_at=captured or CollectionProvenance().captured_at,
        metadata={"legacy_source": "CyborgAnthropology"},
    )
    return CanonicalRecord(
        source_url=_scalar(record.get("scraper_url")),
        source=SourceSection(
            source_type=_scalar(record.get("scraper_type")),
            created_at=_none(record.get("scraper_date")),
            collected_at=captured or None,
            collector=_scalar(record.get("collector_id")),
            collection_method=_scalar(record.get("source_type")),
            raw_metadata=dict(record.get("scraper_json") or {}),
            raw_ref=_none(record.get("scraper_file")),
        ),
        content=ContentSection(
            text=_scalar(record.get("scraper_text")),
            media_references=media,
        ),
        provenance=[provenance],
        legacy={"research_note_present": bool(record.get("research_note"))},
    )


def from_legacy_collection(record: Mapping[str, Any]) -> CanonicalRecord:
    """Import the former flat NormalizedRecord representation."""
    return NormalizedRecord(**dict(record))


def migrate_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Explicitly migrate known persisted schema versions to 1.0.0."""
    data = dict(payload)
    version = str(data.get("schema_version") or "")
    if version in {"1.0", SCHEMA_VERSION}:
        data["schema_version"] = SCHEMA_VERSION
        if "source" not in data and ("platform" in data or "document_id" in data):
            return NormalizedRecord(**data).model_dump(mode="python")
        return data
    raise ValueError(f"unsupported canonical schema version: {version!r}")


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none"} else text


def _none(value: Any) -> str | None:
    return _scalar(value) or None


def _json_cell(value: Any, default: Any) -> Any:
    text = _scalar(value)
    return default if not text else json.loads(text)
