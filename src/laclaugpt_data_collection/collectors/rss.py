"""Generic RSS/Atom collector inspired by CyborgAnthropology collector modules."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from ..models import CollectionProvenance, NormalizedRecord
from .base import CollectionResult


class RSSCollector:
    def __init__(self, feed_urls: list[str], *, max_items_per_feed: int = 100) -> None:
        self.feed_urls = feed_urls
        self.max_items_per_feed = max_items_per_feed

    def collect(self) -> CollectionResult:
        try:
            import feedparser
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install laclaugpt-data-collection[feeds] for RSS/Atom support") from exc

        result = CollectionResult()
        for feed_url in self.feed_urls:
            result.requests_seen += 1
            parsed = feedparser.parse(feed_url)
            result.bodies_seen += 1
            entries = list(parsed.entries[: self.max_items_per_feed])
            result.raw_items_seen += len(entries)
            for entry in entries:
                record = _entry_to_record(feed_url, entry)
                if record:
                    result.records.append(record)
        if not result.records:
            result.warnings.append(result.zero_result_warning or "No feed items collected")
        return result


def _entry_to_record(feed_url: str, entry: Any) -> NormalizedRecord | None:
    link = str(getattr(entry, "link", "") or "")
    title = str(getattr(entry, "title", "") or "")
    summary = str(getattr(entry, "summary", "") or "")
    published = str(
        getattr(entry, "published", "")
        or getattr(entry, "updated", "")
        or datetime.now(timezone.utc).isoformat()
    )
    source_id = str(getattr(entry, "id", "") or link or f"{title}|{published}")
    document_id = hashlib.sha256(source_id.encode("utf-8")).hexdigest()
    if not (link or title or summary):
        return None
    author = str(getattr(entry, "author", "") or "")
    return NormalizedRecord(
        document_id=document_id,
        platform="rss",
        author=author,
        timestamp=published,
        source_url=link,
        text="\n\n".join(part for part in (title, summary) if part),
        collection_provenance=CollectionProvenance(
            module="rss-feedparser",
            visited_url=feed_url,
            api_url=link,
            transformations=["rss-atom-parse", "map-entry"],
        ),
    )
