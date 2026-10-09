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
            entries = list(parsed.entries[: self.max_items_per_feed])
            result.raw_items_seen += len(entries)
            for entry in entries:
                record = _entry_to_record(feed_url, entry, feed_language=_feed_language(parsed))
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


def _feed_language(parsed: Any) -> str:
    """The feed-level declared language, or "" when the parser does not report one.

    `feedparser` returns a dict-like `parsed.feed`, but a parser stub (and an Atom
    document with no feed-level language) may carry no `feed` at all, or carry it as
    a plain object rather than a mapping. Reading the attribute unconditionally made
    every such parse raise AttributeError, which the plugin layer surfaced as a
    whole-source collection failure -- so a missing *optional* language field took
    down feeds that had parsed perfectly well.

    A declared language is a hint; its absence is not an error. The per-entry
    language is resolved later by `resolve_language`, which falls back to content
    detection, so nothing is lost by returning "" here.
    """
    feed = getattr(parsed, "feed", None)
    if isinstance(feed, dict):
        return str(feed.get("language", "") or "")
    language = getattr(feed, "language", "")
    return str(language or "")


def _entry_to_record(feed_url: str, entry: Any, *, feed_language: str = "") -> NormalizedRecord | None:
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
    from ..language import resolve_language

    language, language_method = resolve_language(
        "\n\n".join(part for part in (title, summary) if part),
        declared=str(getattr(entry, "language", "") or feed_language),
    )
    return NormalizedRecord(
        document_id=document_id,
        platform="rss",
        author=author,
        language=language,
        timestamp=published,
        source_url=link,
        text="\n\n".join(part for part in (title, summary) if part),
        raw_payload=raw_entry,
        raw_content_type="application/feed+json",
        collection_provenance=CollectionProvenance(
            module="rss-feedparser",
            visited_url=feed_url,
            api_url=link,
            transformations=["rss-atom-parse", "map-entry"],
            metadata={"source_publication_time_present": bool(published), "language_method": language_method},
        ),
    )
