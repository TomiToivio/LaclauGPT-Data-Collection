"""Generic RSS/Atom collector inspired by CyborgAnthropology collector modules."""
from __future__ import annotations

import hashlib
from typing import Any

from ..extraction.html import extract_visible_text
from ..models import CollectionProvenance, NormalizedRecord
from .base import CollectionResult

# A feed that ships full article bodies is a legitimate full-text source, but one
# pathological feed must not store a book. The cap is deliberately far above any real
# article; when it bites, `metadata.text_truncated` says so (#450).
MAX_FEED_TEXT_CHARS = 200_000


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
    # #296: an aggregator item (Google News and friends) carries the publisher in
    # the entry's `source` element, and its own link is the aggregator's opaque
    # token -- not the article. Record the publisher here, where the data is; the
    # row-level declaration in the manifest says the feed is an aggregator.
    syndication = getattr(entry, "source", None)
    publisher_url = publisher_name = ""
    if hasattr(syndication, "get"):
        publisher_url = str(syndication.get("href") or "")
        publisher_name = str(syndication.get("title") or "")
    from ..language import resolve_language

    # Prefer full publisher-provided article content to a short RSS excerpt (#450): a
    # feed that ships the article body is a legitimate full-text source, and storing only
    # its summary would silently make an excerpt look like the article. The body arrives as
    # HTML, so it is reduced to visible text before it becomes record text.
    parts = getattr(entry, "content", None) or []
    raw_body = "\n\n".join(
        str(part.get("value") or "") for part in parts if hasattr(part, "get")
    )
    body = extract_visible_text(raw_body).text.strip() if raw_body.strip() else ""
    excerpt = "\n\n".join(part for part in (title, summary) if part)
    use_body = len(body) > len(excerpt)
    richest = body if use_body else excerpt
    language, language_method = resolve_language(
        richest,
        declared=str(getattr(entry, "language", "") or feed_language),
    )
    text = richest[:MAX_FEED_TEXT_CHARS]
    metadata: dict[str, Any] = {
        "source_publication_time_present": bool(published),
        "language_method": language_method,
        # Which text this record carries, and whether the cap bit. Without these a
        # truncated record is indistinguishable from a complete one.
        "text_source": "feed-content" if use_body else "feed-excerpt",
        "text_chars": len(text),
        "text_truncated": len(richest) > len(text),
    }
    if publisher_url or publisher_name:
        metadata["publisher_url"] = publisher_url
        metadata["publisher_name"] = publisher_name
    return NormalizedRecord(
        document_id=document_id,
        platform="rss",
        author=author,
        language=language,
        timestamp=published,
        source_url=link,
        text=text,
        raw_payload=raw_entry,
        raw_content_type="application/feed+json",
        collection_provenance=CollectionProvenance(
            module="rss-feedparser",
            visited_url=feed_url,
            api_url=link,
            transformations=["rss-atom-parse", "map-entry"]
            + (["feed-content-to-text"] if use_body else []),
            metadata=metadata,
        ),
    )
