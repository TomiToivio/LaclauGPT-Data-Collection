"""Adapters between external collection tools and LaclauGPT canonical records.

The adapters deliberately keep external-tool quirks out of the canonical schema. Unknown
fields remain in the lossless raw capture and adapter metadata; stable external IDs are
preserved in ``source_native_ids`` for downstream reconciliation.
"""
from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ..models import (
    CanonicalRecord,
    CollectionProvenance,
    ContentSection,
    MediaReference,
    RawCaptureSection,
    SourceSection,
)

ADAPTER_VERSION = "1.0.0"
ExternalTool = Literal["4cat", "zeeschuimer", "dats"]


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _iso_timestamp(value: Any) -> str | None:
    """Normalize common external timestamps without pretending ambiguous values are UTC."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        # Millisecond epochs are common in browser-capture exports.
        seconds = float(value) / 1000.0 if abs(float(value)) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=UTC).isoformat()
    raw = str(value).strip()
    if raw.isdigit():
        return _iso_timestamp(int(raw))
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        # Keep source spelling when the adapter cannot safely infer a timezone/format.
        return raw
    return parsed.isoformat()


def _media_references(value: Any) -> list[MediaReference]:
    refs: list[MediaReference] = []
    for index, item in enumerate(_list(value)):
        if isinstance(item, str):
            refs.append(MediaReference(kind="external", url=item, media_index=index))
            continue
        data = _mapping(item)
        if not data:
            continue
        refs.append(
            MediaReference(
                kind=_text(_first(data, "kind", "type", "media_type", default="external")),
                url=_text(_first(data, "url", "src", "download_url")),
                media_index=index,
                local_ref=_text(_first(data, "local_ref", "path", "file")),
                object_ref=_text(_first(data, "object_ref", "object_key")),
                checksum=_text(_first(data, "checksum", "sha256")),
                metadata={
                    key: val
                    for key, val in data.items()
                    if key
                    not in {
                        "kind",
                        "type",
                        "media_type",
                        "url",
                        "src",
                        "download_url",
                        "local_ref",
                        "path",
                        "file",
                        "object_ref",
                        "object_key",
                        "checksum",
                        "sha256",
                    }
                },
            )
        )
    return refs


def _provenance(
    tool: ExternalTool,
    *,
    captured_at: str | None,
    external_id: str,
    sampling: Mapping[str, Any] | None = None,
) -> CollectionProvenance:
    metadata: dict[str, Any] = {
        "external_tool": tool,
        "adapter_version": ADAPTER_VERSION,
        "external_id": external_id,
    }
    if sampling:
        metadata["sampling"] = dict(sampling)
    return CollectionProvenance(
        collector=f"interop:{tool}",
        collector_version=ADAPTER_VERSION,
        captured_at=captured_at or datetime.now(UTC).isoformat(),
        transformations=[f"{tool}-to-canonical-v{ADAPTER_VERSION}"],
        metadata=metadata,
    )


def import_4cat_record(row: Mapping[str, Any]) -> CanonicalRecord:
    """Convert one 4CAT dataset row to a canonical record.

    4CAT datasource processors expose source-specific columns, so this adapter accepts a
    conservative set of common aliases and retains the complete row losslessly.
    """
    data = dict(row)
    external_id = _text(_first(data, "id", "post_id", "item_id", "document_id"))
    platform = _text(_first(data, "platform", "source", "datasource", default="4cat"))
    source_url = _text(_first(data, "url", "link", "source_url"))
    if not source_url:
        if not external_id:
            raise ValueError("4CAT record requires a URL or stable external ID")
        source_url = f"4cat:{platform}:{external_id}"

    created_at = _iso_timestamp(_first(data, "timestamp", "created_at", "date", "time"))
    collected_at = _iso_timestamp(_first(data, "collected_at", "retrieved_at", "capture_time"))
    author = _text(_first(data, "author", "username", "user", "screen_name"))
    content = _text(_first(data, "text", "body", "content", "message", "description"))
    title = _first(data, "title", "name")
    media = _first(data, "media", "media_urls", "attachments", "images", "videos")
    sampling = _mapping(_first(data, "sampling", "collection", "query_metadata"))

    record = CanonicalRecord(
        source_url=source_url,
        source_native_ids={"4cat_id": external_id} if external_id else {},
        raw_capture=RawCaptureSection(
            payload=data,
            captured_at=collected_at,
            metadata={"preservation": "external-dataset-row", "external_tool": "4cat"},
        ),
        source=SourceSection(
            platform=platform,
            source_type=_text(_first(data, "source_type", "type")),
            author=author,
            created_at=created_at,
            collected_at=collected_at,
            collector="4cat",
            collection_method="external-import",
            language=_text(_first(data, "language", "lang")),
            raw_metadata={"external_tool": "4cat", "sampling": sampling},
        ),
        content=ContentSection(
            text=content,
            title=_text(title) if title is not None else None,
            language=_text(_first(data, "language", "lang")) or None,
            media_references=_media_references(media),
        ),
        provenance=[
            _provenance(
                "4cat",
                captured_at=collected_at,
                external_id=external_id,
                sampling=sampling,
            )
        ],
    )
    record.refresh_human_readable()
    return record


def export_4cat_projection(record: CanonicalRecord) -> dict[str, Any]:
    """Return a safe flat projection suitable for tabular 4CAT-style interchange."""
    provenance = record.provenance[-1] if record.provenance else None
    return {
        "id": record.source_native_ids.get("4cat_id")
        or record.source_native_ids.get("document_id")
        or record.source_url,
        "url": record.source_url,
        "platform": record.source.platform,
        "source_type": record.source.source_type,
        "author": record.source.author,
        "timestamp": record.source.created_at or "",
        "collected_at": record.source.collected_at or "",
        "language": record.source.language or record.content.language or "",
        "title": record.content.title or "",
        "text": record.content.text,
        "media": [item.model_dump(mode="json") for item in record.content.media_references],
        "laclaugpt_schema_version": record.schema_version,
        "laclaugpt_provenance": provenance.model_dump(mode="json") if provenance else {},
    }


def import_zeeschuimer_record(payload: Mapping[str, Any]) -> CanonicalRecord:
    """Convert a Zeeschuimer NDJSON/JSON item into a canonical record."""
    envelope = dict(payload)
    nested = _mapping(_first(envelope, "data", "payload", "item"))
    data = {**envelope, **nested}
    external_id = _text(_first(data, "id", "post_id", "item_id", "pk", "rest_id"))
    platform = _text(
        _first(data, "platform", "source_platform", "source", "type", default="zeeschuimer")
    )
    source_url = _text(_first(data, "url", "permalink", "web_url", "source_url"))
    if not source_url:
        if not external_id:
            raise ValueError("Zeeschuimer record requires a URL or stable external ID")
        source_url = f"zeeschuimer:{platform}:{external_id}"

    captured_at = _iso_timestamp(
        _first(envelope, "timestamp_collected", "collected_at", "captured_at", "timestamp_capture")
    )
    created_at = _iso_timestamp(_first(data, "created_at", "timestamp", "date", "taken_at"))
    sampling = {
        key: envelope[key]
        for key in (
            "query",
            "seed",
            "search_terms",
            "discovery_method",
            "collection_method",
            "tab_url",
        )
        if envelope.get(key) not in (None, "")
    }
    media = _first(data, "media", "attachments", "media_urls", "images", "videos")

    record = CanonicalRecord(
        source_url=source_url,
        source_native_ids={"zeeschuimer_id": external_id} if external_id else {},
        raw_capture=RawCaptureSection(
            payload=envelope,
            captured_at=captured_at,
            metadata={"preservation": "external-browser-capture", "external_tool": "zeeschuimer"},
        ),
        source=SourceSection(
            platform=platform,
            source_type=_text(_first(data, "source_type", "post_type", "type")),
            author=_text(_first(data, "author", "username", "user", "screen_name", "handle")),
            created_at=created_at,
            collected_at=captured_at,
            collector="zeeschuimer",
            collection_method="browser-extension-import",
            language=_text(_first(data, "language", "lang")),
            raw_metadata={"external_tool": "zeeschuimer", "sampling": sampling},
        ),
        content=ContentSection(
            text=_text(_first(data, "text", "body", "content", "message", "caption")),
            title=_text(_first(data, "title", "name")) or None,
            language=_text(_first(data, "language", "lang")) or None,
            media_references=_media_references(media),
        ),
        provenance=[
            _provenance(
                "zeeschuimer",
                captured_at=captured_at,
                external_id=external_id,
                sampling=sampling,
            )
        ],
    )
    record.refresh_human_readable()
    return record


def import_dats_document(document: Mapping[str, Any]) -> CanonicalRecord:
    """Import the source-document portion of a DATS export.

    Codes, annotations and AI analyses intentionally remain downstream Analysis concerns.
    """
    data = dict(document)
    metadata = _mapping(data.get("metadata"))
    document_id = _text(_first(data, "document_id", "id", "uuid"))
    project_id = _text(_first(data, "project_id", default=metadata.get("project_id")))
    source_url = _text(_first(data, "source_url", "url", default=metadata.get("url")))
    if not source_url:
        if not document_id:
            raise ValueError("DATS document requires a source URL or document ID")
        source_url = f"dats:{project_id or 'project'}:{document_id}"

    native_ids = {"dats_document_id": document_id} if document_id else {}
    if project_id:
        native_ids["dats_project_id"] = project_id

    file_refs = [
        _text(item)
        for item in _list(_first(data, "file_references", "files", "file", "path"))
        if _text(item)
    ]
    media = _first(data, "media", "media_references", "attachments")
    created_at = _iso_timestamp(_first(data, "created_at", "date", default=metadata.get("created_at")))
    imported_at = datetime.now(UTC).isoformat()

    record = CanonicalRecord(
        source_url=source_url,
        source_native_ids=native_ids,
        raw_capture=RawCaptureSection(
            payload=data,
            captured_at=imported_at,
            metadata={
                "preservation": "external-project-document",
                "external_tool": "dats",
                "codes_and_annotations_imported": False,
            },
        ),
        source=SourceSection(
            platform=_text(_first(data, "platform", default=metadata.get("platform"))) or "dats",
            source_type=_text(_first(data, "source_type", "type", default=metadata.get("type"))),
            author=_text(_first(data, "author", default=metadata.get("author"))),
            created_at=created_at,
            collected_at=imported_at,
            collector="dats",
            collection_method="project-document-import",
            language=_text(_first(data, "language", "lang", default=metadata.get("language"))),
            raw_metadata={
                "external_tool": "dats",
                "dats_project_id": project_id,
                "dats_metadata": metadata,
            },
        ),
        content=ContentSection(
            text=_text(_first(data, "text", "content", "body")),
            title=_text(_first(data, "title", "name")) or None,
            language=_text(_first(data, "language", "lang", default=metadata.get("language")))
            or None,
            media_references=_media_references(media),
            file_references=file_refs,
        ),
        provenance=[
            _provenance("dats", captured_at=imported_at, external_id=document_id)
        ],
    )
    record.refresh_human_readable()
    return record


def import_external_record(tool: ExternalTool, payload: Mapping[str, Any]) -> CanonicalRecord:
    """Dispatch an external source document to the correct adapter."""
    if tool == "4cat":
        return import_4cat_record(payload)
    if tool == "zeeschuimer":
        return import_zeeschuimer_record(payload)
    if tool == "dats":
        return import_dats_document(payload)
    raise ValueError(f"unsupported external tool: {tool}")


def read_external_records(path: str | Path, *, tool: ExternalTool) -> list[CanonicalRecord]:
    """Read JSON, JSONL/NDJSON, or CSV exports through an interoperability adapter."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        with source.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    elif suffix in {".jsonl", ".ndjson"}:
        with source.open("r", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
    elif suffix == ".json":
        with source.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if isinstance(raw, list):
            rows = raw
        elif isinstance(raw, Mapping):
            candidate = _first(raw, "items", "documents", "data")
            rows = candidate if isinstance(candidate, list) else [raw]
        else:
            raise ValueError("JSON export must contain an object or array of objects")
    else:
        raise ValueError(f"unsupported external file type: {suffix}")
    return [import_external_record(tool, _mapping(row)) for row in rows]


def write_records(
    records: Iterable[CanonicalRecord],
    path: str | Path,
    *,
    projection: Literal["canonical", "4cat"] = "canonical",
) -> None:
    """Write portable canonical or 4CAT-projection JSON/JSONL/CSV/Parquet exports."""
    destination = Path(path)
    rows: list[dict[str, Any]] = []
    for record in records:
        if projection == "4cat":
            rows.append(export_4cat_projection(record))
        else:
            rows.append(record.model_dump(mode="json"))

    suffix = destination.suffix.lower()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".json":
        destination.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if suffix in {".jsonl", ".ndjson"}:
        destination.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        return
    if suffix == ".csv":
        if not rows:
            destination.write_text("", encoding="utf-8")
            return
        fieldnames = sorted({key for row in rows for key in row})
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        key: json.dumps(value, ensure_ascii=False)
                        if isinstance(value, (dict, list))
                        else value
                        for key, value in row.items()
                    }
                )
        return
    if suffix == ".parquet":
        try:
            import pyarrow as pa  # type: ignore[import-not-found]
            import pyarrow.parquet as pq  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "Parquet export requires the optional 'interop' dependency: "
                "pip install -e '.[interop]'"
            ) from exc
        pq.write_table(pa.Table.from_pylist(rows), destination)
        return
    raise ValueError(f"unsupported export file type: {suffix}")
