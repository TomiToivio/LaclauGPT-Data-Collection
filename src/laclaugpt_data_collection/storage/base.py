"""Storage protocols used by collectors and orchestration."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ..models import NormalizedRecord


class RecordStore(Protocol):
    def upsert(self, record: NormalizedRecord) -> None: ...

    def upsert_many(self, records: Iterable[NormalizedRecord]) -> None: ...

    def contains(self, platform: str, document_id: str) -> bool: ...


class ObjectStore(Protocol):
    def put_bytes(self, key: str, payload: bytes, *, content_type: str = "application/octet-stream") -> str: ...

    def put_text(self, key: str, payload: str, *, content_type: str = "text/plain; charset=utf-8") -> str: ...
