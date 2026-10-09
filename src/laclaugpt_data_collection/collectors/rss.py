"""Generic RSS/Atom collector inspired by CyborgAnthropology collector modules."""
from __future__ import annotations

import hashlib
from typing import Any

from ..models import CollectionProvenance, NormalizedRecord
from .base import CollectionResult


class RSSCollector:
    def __init__(
        self,
        feed_urls: list[str],
        *,
        max_items_per_feed: int = 100,
        source_name: str = "",
    ) -> None:
        self.feed_urls = feed_urls
        self.max_items_per_feed = max_items_per_feed
        # Optional human label for the configured source. Warnings from the
        # collection runner are aggregated anonymously, so without this a
        # zero-item feed is indistinguishable from any other source.
        self.source_name = source_name

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
            # A feed's own <language> element is the publisher's declaration
            # (#238); it is passed down so an entry never has to guess what the
            # feed already states.
            feed_language = str(getattr(parsed, "feed", {}).get("language", "") or "")
            entries = list(parsed.entries[: self.max_items_per_feed])
            result.raw_items_seen += len(entries)
            for entry in entries:
                record = _entry_to_record(feed_url, entry, feed_language=feed_language)
                if record:
                    result.records.append(record)
        if not result.records:
            if result.bodies_seen and not result.raw_items_seen:
                # Parsed cleanly and carried nothing: a publisher-side empty
                # feed, not payload drift. Report it by name so the source is
                # identifiable in the aggregated cycle warnings.
                result.warnings.append(result.empty_feed_warning(self.source_name))
            else:
                result.warnings.append(result.zero_result_warning or "No feed items collected")
        return result


def _entry_to_record(
    feed_url: str, entry: Any, *, feed_language: str = ""
) -> NormalizedRecord | None:
    link = str(getattr(entry, "link", "") or "")
    title = str(getattr(entry, "title", "") or "")
    summary = str(getattr(entry, "summary", "") or "")
    # Preserve a genuinely missing publication time as missing. Collection time
    # must never masquerade as source publication time in realtime scheduling.
    published = str(getattr(entry, "published", "") or getattr(entry, "updated", "") or "")
    source_id = str(getattr(entry, "id", "") or link or f"{title}|{published}")
    document_id = hashlib.sha256(source_id.encode("utf-8")).hexdigest()
    if not (link or title or summary):
        return None
    author = str(getattr(entry, "author", "") or "")
    raw_entry = dict(entry) if hasattr(entry, "items") else {"value": str(entry)}
    # Issue #238: an RSS/Atom record used to carry no language at all. Prefer
    # the feed's declared <language>, then the entry's own, then detect from
    # the text; the record says which of the three it was.
    from ..language import language_metadata, resolve_language

    body = "\n\n".join(part for part in (title, summary) if part)
    tag, tag_source = resolve_language(body, {"language": feed_language}, raw_entry)
    return NormalizedRecord(
        document_id=document_id,
        platform="rss",
        author=author,
        timestamp=published,
        source_url=link,
        text=body,
        raw_payload=raw_entry,
        raw_content_type="application/feed+json",
        collection_provenance=CollectionProvenance(
            module="rss-feedparser",
            visited_url=feed_url,
            api_url=link,
            transformations=["rss-atom-parse", "map-entry"],
            metadata={
                "source_publication_time_present": bool(published),
                **language_metadata(tag, tag_source),
            },
        ),
    )
