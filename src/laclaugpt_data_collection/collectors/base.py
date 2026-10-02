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
    next_cursor: str | None = None
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

    def empty_feed_warning(self, source: str = "") -> str:
        """Warning for a feed that was fetched, parsed, and simply carried no items.

        This is deliberately distinct from :attr:`zero_result_warning`. A valid
        but empty feed is a *publisher-side* condition: the document parsed
        (``bozo=False``) and there is no payload shape to adapt to, so the
        generic "check endpoint/payload drift" hint sends the reader after a
        bug that does not exist. Naming the source is what makes the cycle
        actionable, because the collected warnings are aggregated anonymously.
        """
        label = f"{source}: " if source else ""
        return (
            f"{label}response body captured but the feed contained no items; "
            "check the publisher's feed (not parser drift)"
        )


class Collector(Protocol):
    def collect(self) -> CollectionResult: ...
