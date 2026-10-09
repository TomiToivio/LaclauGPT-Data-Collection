"""Storage protocols used by collectors and orchestration."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ..models import CanonicalRecord


class RecordStore(Protocol):
    def upsert(self, record: CanonicalRecord) -> bool:
        """Persist one record; return True when it was newly created.

        The return value exists so a collection cycle can report *corpus growth*
        (new documents) separately from *sync operations* (upserts, which include
        re-writes of records already in the store). A store that cannot tell the
        difference may return ``False``; callers must never infer growth from the
        operation count alone.
        """
        ...

    def upsert_many(self, records: Iterable[CanonicalRecord]) -> None: ...

    def contains(self, source_url: str) -> bool: ...


class ObjectStore(Protocol):
    def put_bytes(self, key: str, payload: bytes, *, content_type: str = "application/octet-stream") -> str: ...

    def put_text(self, key: str, payload: str, *, content_type: str = "text/plain; charset=utf-8") -> str: ...
