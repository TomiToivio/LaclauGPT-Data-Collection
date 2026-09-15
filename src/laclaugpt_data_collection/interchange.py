"""Canonical record serialization and bounded legacy/researcher adapters."""
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
    HumanReadableSection,
    IntermediateSection,
    MediaReference,
    NormalizedRecord,
    RawCaptureSection,
    SourceSection,
)

NESTED_FIELDS = (
    "source_native_ids",
    "raw_capture",
    "source",
    "content",
    "intermediate",
    "evidence",
    "analysis",
    "human_readable",
    "provenance",
    "review",
    "legacy",
)

# Stable researcher-facing columns shared conceptually with Analysis/Visualization.
# Collection emits empty analysis/intermediate aliases until downstream stages fill them.
RESEARCH_COLUMNS = (
    "raw_ref",
    "raw_payload_json",
    "source_platform",
    "source_type",
    "source_author",
    "source_author_fullname",
    "source_country",
    "source_language",
    "source_timestamp",
    "source_text",
    "whisper_transcript",
    "whisper_language",
    "whisper_translated",
    "ocr_1", "ocr_2", "ocr_3", "ocr_4", "ocr_5", "ocr_6",
    "frame_1", "frame_2", "frame_3", "frame_4", "frame_5", "frame_6",
    "summary_analysis",
    "entities",
    "topics",
    "positive",
    "neutral",
    "negative",
    "formula_of_populism_analysis",
    "human_readable_summary",
    "human_readable_markdown",
)


def _research_projection(record: CanonicalRecord) -> dict[str, str]:
    raw_payload = record.raw_capture.payload
    source = record.source
    return {
        "raw_ref": record.raw_capture.ref or source.raw_ref or "",
        "raw_payload_json": "" if raw_payload is None else json.dumps(raw_payload, ensure_ascii=False, sort_keys=True),
        "source_platform": source.platform,
        "source_type": source.source_type,
        "source_author": source.author,
        "source_author_fullname": source.author_fullname,
        "source_country": source.country,
        "source_language": source.language,
        "source_timestamp": source.created_at or "",
        "source_text": record.content.text,
        "whisper_transcript": "",
        "whisper_language": "",
        "whisper_translated": "",
        **{f"ocr_{index}": "" for index in range(1, 7)},
        **{f"frame_{index}": "" for index in range(1, 7)},
        "summary_analysis": "",
        "entities": "",
        "topics": "",
        "positive": "",
        "neutral": "",
        "negative": "",
        "formula_of_populism_analysis": "",
        "human_readable_summary": record.human_readable.summary,
        "human_readable_markdown": record.human_readable.markdown,
    }


def to_flat_row(record: CanonicalRecord) -> dict[str, str]:
    payload = record.model_dump(mode="json")
    return {
        "schema_version": record.schema_version,
        "source_url": record.source_url,
        **{
            key: json.dumps(payload[key], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for key in NESTED_FIELDS
        },
        **_research_projection(record),
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
    """Write canonical JSON sections plus stable wide researcher/legacy columns."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = ["schema_version", "source_url", *NESTED_FIELDS, *RESEARCH_COLUMNS]
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
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
    """MongoDB stores the complete four-layer document, never only a view row."""
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
    raw_payload = record.get("scraper_json")
    raw_ref = _none(record.get("scraper_file"))
    canonical = CanonicalRecord(
        source_url=_scalar(record.get("scraper_url")),
        raw_capture=RawCaptureSection(
            ref=raw_ref,
            payload=raw_payload,
            captured_at=captured or None,
            content_type="application/json" if raw_payload is not None else None,
            metadata={"preservation": "legacy-import"},
        ),
        source=SourceSection(
            source_type=_scalar(record.get("scraper_type")),
            created_at=_none(record.get("scraper_date")),
            collected_at=captured or None,
            collector=_scalar(record.get("collector_id")),
            collection_method=_scalar(record.get("source_type")),
            raw_metadata=dict(raw_payload or {}),
            raw_ref=raw_ref,
        ),
        content=ContentSection(
            text=_scalar(record.get("scraper_text")),
            media_references=media,
        ),
        provenance=[provenance],
        legacy={"research_note_present": bool(record.get("research_note"))},
    )
    canonical.refresh_human_readable()
    return canonical


def from_legacy_collection(record: Mapping[str, Any]) -> CanonicalRecord:
    """Import the former flat NormalizedRecord representation."""
    return NormalizedRecord(**dict(record))


def migrate_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Migrate 1.0-era records to the four-layer 1.1.0 contract without data loss."""
    data = dict(payload)
    version = str(data.get("schema_version") or "")
    if version in {"1.0", "1.0.0"}:
        if "source" not in data and ("platform" in data or "document_id" in data):
            return NormalizedRecord(**data).model_dump(mode="python")
        source = dict(data.get("source") or {})
        content = dict(data.get("content") or {})
        raw_ref = _scalar(source.get("raw_ref")) or None
        data["raw_capture"] = data.get("raw_capture") or RawCaptureSection(
            ref=raw_ref,
            payload=None,
            metadata={
                "preservation": (
                    "legacy-durable-reference" if raw_ref else "compatibility-missing-original"
                )
            },
        ).model_dump(mode="python")
        data["intermediate"] = data.get("intermediate") or IntermediateSection().model_dump(mode="python")
        preview = _scalar(content.get("text"))
        data["human_readable"] = data.get("human_readable") or HumanReadableSection(
            summary=preview[:500],
            markdown=(f"# Research record\n\n## Collected content\n{preview[:2000]}" if preview else "# Research record"),
            generator="laclaugpt-data-collection-migration",
            sections={"content": preview[:2000]},
        ).model_dump(mode="python")
        data["schema_version"] = SCHEMA_VERSION
        return data
    if version == SCHEMA_VERSION:
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
