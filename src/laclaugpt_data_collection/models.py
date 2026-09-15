"""Backend-neutral data models shared across LaclauGPT modules."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


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

    @property
    def dedup_key(self) -> tuple[str, str]:
        return self.platform, self.document_id
