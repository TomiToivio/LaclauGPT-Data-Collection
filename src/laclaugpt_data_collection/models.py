<<<<<<< HEAD
"""Backend-neutral data models shared across LaclauGPT modules."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .canonical import normalize_source_uri


class CollectionProvenance(BaseModel):
    collector: str = "laclaugpt-data-collection"
    collector_version: str = "0.1.0"
    captured_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    capture_id: str = ""
    run_id: str = ""
    module: str = ""
    module_version: str = ""
    git_commit: str = ""
    visited_url: str = ""
    api_url: str = ""
    transformations: list[str] = Field(default_factory=list)


class MediaReference(BaseModel):
    kind: str
    url: str
    media_index: int = 0
    object_ref: str = ""
    checksum: str = ""


class NormalizedRecord(BaseModel):
    schema_version: str = "1.0"
    document_id: str
    platform: str
    author: str = ""
    author_fullname: str = ""
    timestamp: str = ""
    unix_timestamp: int = 0
    source_url: str = ""
    text: str = ""
    language: str = ""
    parent_document_id: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    engagement: dict[str, Any] = Field(default_factory=dict)
    media_references: list[MediaReference] = Field(default_factory=list)
    raw_ref: str = ""
    collection_provenance: CollectionProvenance = Field(default_factory=CollectionProvenance)

    @field_validator("source_url")
    @classmethod
    def canonical_source_url(cls, value: str) -> str:
        return normalize_source_uri(value) if value else value

    @property
    def canonical_identity(self) -> str:
        return self.source_url or f"urn:laclaugpt:{self.platform}:{self.document_id}"

    @property
    def dedup_key(self) -> tuple[str, str]:
        return self.platform, self.canonical_identity
=======
"""Canonical, storage-neutral data models for LaclauGPT Collection.

Collection owns source identity, source metadata, source content references and
collection provenance. Analysis enriches the same logical record later.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0.0"
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
    capture_id: str = ""
    run_id: str = ""
    module: str = ""
    module_version: str = ""
    git_commit: str = ""
    visited_url: str = ""
    api_url: str = ""
    transformations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MediaReference(Model):
    kind: str
    url: str = ""
    media_index: int = 0
    local_ref: str = ""
    object_ref: str = ""
    checksum: str = ""
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
    parent_source_url: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    raw_ref: str | None = None


class ContentSection(Model):
    text: str = ""
    title: str | None = None
    language: str | None = None
    translated_text: str | None = None
    media_references: list[MediaReference] = Field(default_factory=list)
    file_references: list[str] = Field(default_factory=list)


class CanonicalRecord(Model):
    """Collection-populated portion of the project-wide canonical record."""

    schema_version: str = SCHEMA_VERSION
    source_url: str
    source_native_ids: dict[str, str] = Field(default_factory=dict)
    source: SourceSection = Field(default_factory=SourceSection)
    content: ContentSection = Field(default_factory=ContentSection)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    analysis: dict[str, Any] = Field(default_factory=dict)
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


class NormalizedRecord(CanonicalRecord):
    """Compatibility constructor for existing collectors.

    Existing collectors may still construct the old flat envelope. Persisted
    output is the canonical nested record, so this is an adapter rather than a
    competing schema.
    """

    def __init__(self, **data: Any) -> None:
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
            provenance = []
            if collection_provenance is not None:
                provenance = [collection_provenance]
            data.update(
                source_url=source_url,
                source_native_ids={"document_id": document_id} if document_id else {},
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
        super().__init__(**data)

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
        return int(self.source.raw_metadata.get("unix_timestamp") or 0)

    @property
    def text(self) -> str:
        return self.content.text

    @property
    def language(self) -> str:
        return self.source.language

    @property
    def parent_document_id(self) -> str | None:
        value = self.source.raw_metadata.get("parent_document_id")
        return str(value) if value else None

    @property
    def hashtags(self) -> list[str]:
        return list(self.source.raw_metadata.get("hashtags") or [])

    @property
    def mentions(self) -> list[str]:
        return list(self.source.raw_metadata.get("mentions") or [])

    @property
    def engagement(self) -> dict[str, Any]:
        return dict(self.source.raw_metadata.get("engagement") or {})

    @property
    def media_references(self) -> list[MediaReference]:
        return self.content.media_references

    @property
    def raw_ref(self) -> str:
        return self.source.raw_ref or ""

    @property
    def collection_provenance(self) -> CollectionProvenance:
        return self.provenance[0] if self.provenance else CollectionProvenance()
>>>>>>> d32811c4af08a512bdf38f22ff0b072a6f479cf5
