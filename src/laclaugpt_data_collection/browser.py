"""Typed local browser-capture boundary; no browser or network side effects."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .collectors.ingest import ingest_capture
from .models import NormalizedRecord
from .storage.base import RecordStore


class BrowserCapture(BaseModel):
    visited_url: str
    response_url: str
    response: Any
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    capture_id: str = ""
def ingest_browser_capture(capture: BrowserCapture, store: RecordStore | None = None) -> list[NormalizedRecord]:
    records=ingest_capture(response=capture.response,visited_url=capture.visited_url,response_url=capture.response_url,metadata={"captured_at":capture.captured_at.isoformat(),"capture_id":capture.capture_id,"source_platform_url":capture.visited_url})
    if store:
        store.upsert_many(records)
    return records
