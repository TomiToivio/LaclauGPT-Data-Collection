"""Collector interfaces shared by source adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..models import NormalizedRecord


@dataclass(slots=True)
class CollectionResult:
    records: list[NormalizedRecord] = field(default_factory=list)
    requests_seen: int = 0
    bodies_seen: int = 0
    raw_items_seen: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def zero_result_warning(self) -> str | None:
        if self.records:
            return None
        if self.requests_seen and not self.bodies_seen:
            return "Requests were captured but no response bodies were available. Check auth/capture permissions."
        if self.bodies_seen and not self.raw_items_seen:
            return "Response bodies were captured but parsers emitted no items. Check endpoint/payload drift."
        return "No collection activity was observed. Check source configuration and connectivity."


class Collector(Protocol):
    def collect(self) -> CollectionResult: ...
