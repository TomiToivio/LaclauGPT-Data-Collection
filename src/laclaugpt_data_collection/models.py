"""Canonical, storage-neutral data models for LaclauGPT Collection.

Collection owns source identity, raw source preservation, normalized source metadata,
source-derived content and collection provenance. Analysis enriches the same logical
record later. The four-layer research contract is additive: raw capture, intermediate
stage output, canonical analysis and a researcher-readable summary must survive every
storage adapter.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.1.0"
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def canonicalize_source_url(value: str) -> str:
    """Deterministically normalize a web URL while preserving URI-like IDs."""
    value = value.strip()
    if not value:
        return value
    parts = urlsplit(value)
    if parts.scheme in {"http", "https"} and parts.netloc:
        query = [
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_KEYS
        ]
        path = parts.path
        if path != "/":
            path = path.rstrip("/")
        return urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                path,
                urlencode(query, doseq=True),
                "",
            )
        )
    return value


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CollectionProvenance(Model):
    provenance_id: str = ""
    stage: str = "collection"
    collector: str = "laclaugpt-data-collection"
    collector_version: str = "0.1.0"
    captured_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    created_at: str | None = None
    capture_id: str = ""
    run_id: str = ""
    method: str = ""
    module: str = ""
    module_version: str = ""
    git_commit: str = ""
    model: str | None = None
    model_version: str | None = None
    visited_url: str = ""
    api_url: str = ""
    input_refs: list[str] = Field(default_factory=list)
    transformations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawCaptureSection(Model):
    """Lossless source material received by the collector.

    Production collectors should retain the exact payload inline, an immutable raw_ref,
    or both. Compatibility imports may carry a reconstructed snapshot but must mark it in
    metadata rather than claiming it is byte-for-byte source material.
    """

    ref: str | None = None
    payload: Any | None = None
    checksum: str | None = None
    content_type: str | None = None
    captured_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def preserved(self) -> bool:
        return bool(self.ref) or self.payload is not None


class IntermediateSection(Model):
    """Lossless preprocessing/stage outputs retained before final analysis."""

    asr: list[dict[str, Any]] = Field(default_factory=list)
    ocr: list[dict[str, Any]] = Field(default_factory=list)
    frames: list[dict[str, Any]] = Field(default_factory=list)
    frame_analysis: list[dict[str, Any]] = Field(default_factory=list)
    translations: list[dict[str, Any]] = Field(default_factory=list)
    stage_outputs: dict[str, Any] = Field(default_factory=dict)


class HumanReadableSection(Model):
    summary: str = ""
    markdown: str = ""
    generated_at: str | None = None
    generator: str = "laclaugpt-data-collection"
    sections: dict[str, str] = Field(default_factory=dict)


class MediaReference(Model):
    kind: str = ""
    media_type: str = ""
    ref: str = ""
    url: str = ""
    media_index: int = 0
    local_ref: str = ""
    object_ref: str = ""
    checksum: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceLocation(Model):
    """Factual location metadata provided directly by the source.

    Collection preserves source-provided place names/coordinates and their provenance.
    Geocoder-, model- or researcher-inferred locations belong to downstream analysis and
    must never be written here as if they were source truth.
    """

    name: str = ""
    country: str = ""
    region: str = ""
    locality: str = ""
    latitude: float | None = None
    longitude: float | None = None
    source_field: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceSection(Model):
    platform: str = ""
    source_type: str = ""
    author: str = ""
    author_fullname: str = ""
    created_at: str | None = None
    collected_at: str | None = None
    collector: str = ""
    collection_method: str = ""
    language: str = ""
    country: str = ""
    locations: list[SourceLocation] = Field(default_factory=list)
    parent_source_url: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    raw_ref: str | None = None


class ContentSection(Model):
    text: str = ""
    title: str | None = None
    language: str | None = None
    translated_text: str | None = None
    transcripts: list[dict[str, Any]] = Field(default_factory=list)
    ocr: list[dict[str, Any]] = Field(default_factory=list)
    frames: list[dict[str, Any]] = Field(default_factory=list)
    media_references: list[MediaReference] = Field(default_factory=list)
    file_references: list[Any] = Field(default_factory=list)


class CanonicalRecord(Model):
    """Collection-populated portion of the project-wide canonical record."""

    fixture_version: str | None = None
    schema_version: str = SCHEMA_VERSION
    source_url: str
    source_native_ids: dict[str, str] = Field(default_factory=dict)
    raw_capture: RawCaptureSection = Field(default_factory=RawCaptureSection)
    source: SourceSection = Field(default_factory=SourceSection)
    content: ContentSection = Field(default_factory=ContentSection)
    intermediate: IntermediateSection = Field(default_factory=IntermediateSection)
    source_units: list[dict[str, Any]] = Field(default_factory=list)
    alignments: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    analysis: dict[str, Any] = Field(default_factory=dict)
    human_readable: HumanReadableSection = Field(default_factory=HumanReadableSection)
    provenance: list[CollectionProvenance] = Field(default_factory=list)
    review: dict[str, Any] = Field(default_factory=dict)
    legacy: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_url")
    @classmethod
    def _canonicalize_identity(cls, value: str) -> str:
        normalized = canonicalize_source_url(value)
        if not normalized:
            raise ValueError("source_url or stable URI-like identifier is required")
        return normalized

    @property
    def dedup_key(self) -> str:
        return self.source_url

    def refresh_human_readable(self) -> None:
        """Create the collection-stage researcher summary without model inference."""
        source_bits = [self.source.platform or "source"]
        if self.source.author:
            source_bits.append(f"by {self.source.author}")
        source_line = " ".join(source_bits)
        text = (self.content.text or "").strip()
        preview = text[:500] + ("…" if len(text) > 500 else "")
        raw_status = self.raw_capture.ref or (
            "inline raw payload" if self.raw_capture.payload is not None else "raw capture unavailable"
        )
        summary = preview or f"Collected {source_line}."
        sections = {
            "source": f"{source_line}; identity: {self.source_url}",
            "raw_capture": str(raw_status),
            "content": preview or "No normalized text content.",
            "analysis": "Analysis has not yet been run.",
        }
        self.human_readable = HumanReadableSection(
            summary=summary,
            markdown=(
                f"# Research record\n\n## Source\n{sections['source']}\n\n"
                f"## Raw capture\n{sections['raw_capture']}\n\n"
                f"## Collected content\n{sections['content']}\n\n"
                "## Analysis\nAnalysis has not yet been run."
            ),
            generated_at=datetime.now(UTC).isoformat(),
            sections=sections,
        )


class NormalizedRecord(CanonicalRecord):
    """Compatibility constructor for existing collectors.

    Existing collectors may still construct the old flat envelope. Persisted output is
    the canonical nested record, so this is an adapter rather than a competing schema.
    """

    def __init__(self, **data: Any) -> None:
        original = dict(data)
        raw_payload = data.pop("raw_payload", None)
        raw_content_type = str(data.pop("raw_content_type", "") or "") or None
        raw_checksum = str(data.pop("raw_checksum", "") or "") or None
        raw_capture = data.get("raw_capture")

        if "source" not in data and ("platform" in data or "document_id" in data):
            document_id = str(data.pop("document_id", "") or "")
            platform = str(data.pop("platform", "") or "")
            source_url = str(data.pop("source_url", "") or "")
            if not source_url:
                if not document_id:
                    raise ValueError("source_url or document_id is required")
                source_url = f"{platform or 'source'}:{document_id}"
            timestamp = str(data.pop("timestamp", "") or "")
            unix_timestamp = int(data.pop("unix_timestamp", 0) or 0)
            author = str(data.pop("author", "") or "")
            author_fullname = str(data.pop("author_fullname", "") or "")
            language = str(data.pop("language", "") or "")
            parent_document_id = data.pop("parent_document_id", None)
            hashtags = list(data.pop("hashtags", []) or [])
            mentions = list(data.pop("mentions", []) or [])
            engagement = dict(data.pop("engagement", {}) or {})
            media_references = list(data.pop("media_references", []) or [])
            raw_ref = str(data.pop("raw_ref", "") or "")
            collection_provenance = data.pop("collection_provenance", None)
            provenance = [collection_provenance] if collection_provenance is not None else []
            captured_at = getattr(collection_provenance, "captured_at", None)
            if isinstance(collection_provenance, dict):
                captured_at = collection_provenance.get("captured_at")
            if raw_capture is None:
                if raw_payload is None and not raw_ref:
                    raw_payload = original
                    raw_meta = {"preservation": "compatibility-derived-constructor-snapshot"}
                else:
                    raw_meta = {"preservation": "exact-or-durable-reference"}
                raw_capture = RawCaptureSection(
                    ref=raw_ref or None,
                    payload=raw_payload,
                    checksum=raw_checksum,
                    content_type=raw_content_type,
                    captured_at=str(captured_at) if captured_at else None,
                    metadata=raw_meta,
                )
            data.update(
                source_url=source_url,
                schema_version=SCHEMA_VERSION,
                source_native_ids={"document_id": document_id} if document_id else {},
                raw_capture=raw_capture,
                source=SourceSection(
                    platform=platform,
                    author=author,
                    author_fullname=author_fullname,
                    created_at=timestamp or None,
                    language=language,
                    raw_ref=raw_ref or None,
                    raw_metadata={
                        "unix_timestamp": unix_timestamp,
                        "hashtags": hashtags,
                        "mentions": mentions,
                        "engagement": engagement,
                        "parent_document_id": parent_document_id,
                    },
                ),
                content=ContentSection(
                    text=str(data.pop("text", "") or ""),
                    language=language or None,
                    media_references=media_references,
                ),
                provenance=provenance,
            )
        else:
            data["schema_version"] = SCHEMA_VERSION
            if raw_capture is None:
                source = data.get("source")
                source_ref = ""
                if isinstance(source, SourceSection):
                    source_ref = source.raw_ref or ""
                elif isinstance(source, dict):
                    source_ref = str(source.get("raw_ref") or "")
                data["raw_capture"] = RawCaptureSection(
                    ref=source_ref or None,
                    payload=raw_payload,
                    checksum=raw_checksum,
                    content_type=raw_content_type,
                    metadata={
                        "preservation": (
                            "exact-or-durable-reference"
                            if raw_payload is not None or source_ref
                            else "compatibility-missing-original"
                        )
                    },
                )
        super().__init__(**data)
        if not self.human_readable.summary:
            self.refresh_human_readable()

    @property
    def document_id(self) -> str:
        return self.source_native_ids.get("document_id", "")

    @property
    def platform(self) -> str:
        return self.source.platform

    @property
    def author(self) -> str:
        return self.source.author

    @property
    def author_fullname(self) -> str:
        return self.source.author_fullname

    @property
    def timestamp(self) -> str:
        return self.source.created_at or ""

    @property
    def unix_timestamp(self) -> int:
        value = self.source.raw_metadata.get("unix_timestamp", 0)
        return int(value or 0)

    @property
    def parent_document_id(self) -> str | None:
        """Legacy flat-envelope compatibility for reply/comment parent identity."""
        value = self.source.raw_metadata.get("parent_document_id")
        return None if value in (None, "") else str(value)

    @property
    def text(self) -> str:
        return self.content.text

    @property
    def language(self) -> str:
        return self.source.language or self.content.language or ""

    @property
    def hashtags(self) -> list[str]:
        return list(self.source.raw_metadata.get("hashtags", []) or [])

    @property
    def mentions(self) -> list[str]:
        return list(self.source.raw_metadata.get("mentions", []) or [])

    @property
    def engagement(self) -> dict[str, Any]:
        return dict(self.source.raw_metadata.get("engagement", {}) or {})

    @property
    def media_references(self) -> list[MediaReference]:
        return self.content.media_references

    @property
    def raw_ref(self) -> str:
        return self.raw_capture.ref or self.source.raw_ref or ""

    @property
    def collection_provenance(self) -> CollectionProvenance | None:
        return self.provenance[-1] if self.provenance else None
