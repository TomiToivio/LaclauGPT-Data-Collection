"""Storage-neutral canonical source contract for Collection -> Analysis -> Visualization."""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator


def normalize_source_uri(value: str) -> str:
    p = urlsplit(value.strip())
    if not p.scheme:
        raise ValueError('source URI requires a scheme')
    host = p.netloc.lower()
    path = p.path.rstrip('/') or '/'
    return urlunsplit((p.scheme.lower(), host, path, p.query, ''))

class CanonicalSourceRecord(BaseModel):
    schema_version: str = '1.0'
    source_url: str
    native_ids: dict[str,str] = Field(default_factory=dict)
    text: str = ''
    content_type: str = 'document'
    created_at: datetime | None = None
    media_references: list[dict[str,str]] = Field(default_factory=list)
    raw_ref: str = ''
    collection_method: str = ''
    collector: str = 'laclaugpt-data-collection'
    collected_at: datetime | None = None
    provenance: dict[str,str] = Field(default_factory=dict)
    @field_validator('source_url')
    @classmethod
    def canonical_uri(cls, value: str) -> str: return normalize_source_uri(value)
    @property
    def identity(self) -> str: return self.source_url
    def to_mongo_document(self) -> dict: return self.model_dump(mode='json')
