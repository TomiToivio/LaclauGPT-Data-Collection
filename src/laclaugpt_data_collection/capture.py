"""Browser-assisted capture transport and canonical ingestion helpers.

This module is deliberately platform-neutral. Browser extensions and other
capture clients POST a small JSON-compatible payload; platform-specific
normalization remains in collector adapters.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class CaptureError(ValueError):
    """Raised when a browser capture is invalid or unsafe to ingest."""


class BrowserCapture(BaseModel):
    """Stable public contract used by the Firefox extension and local API."""

    schema_version: str = "1.0"
    source_url: str
    platform: str
    captured_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    collection_method: str = "browser-extension"
    post_id: str = ""
    author: str = ""
    text: str = ""
    media_urls: list[str] = Field(default_factory=list)
    api_url: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an absolute http(s) URL")
        return value

    @property
    def capture_id(self) -> str:
        material = json.dumps(
            {
                "platform": self.platform.lower(),
                "source_url": self.source_url,
                "post_id": self.post_id,
                "api_url": self.api_url,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()


def deduplicate_captures(captures: list[BrowserCapture]) -> list[BrowserCapture]:
    """Return captures in first-seen order, removing idempotent duplicates."""
    seen: set[str] = set()
    unique: list[BrowserCapture] = []
    for capture in captures:
        key = capture.capture_id
        if key in seen:
            continue
        seen.add(key)
        unique.append(capture)
    return unique


def capture_payload(capture: BrowserCapture) -> dict[str, Any]:
    """Serialize a capture without leaking runtime-only state."""
    payload = capture.model_dump(mode="json")
    payload["capture_id"] = capture.capture_id
    return payload
