"""Podcast transcript collector (#450).

AI26 is text-first: it uses a transcript the publisher already publishes, and it
never downloads audio or video to produce one. A show that publishes no transcript
yields an explicit warning, not a synthesised stand-in.

The transcript is the page's own visible text with the page chrome removed. Metadata
comes from the page's JSON-LD (``datePublished``, ``headline``, ``author``), because
publisher themes put the publication time there rather than in ``article:published_time``
— checked against a real episode page where only the JSON-LD carried it.

Absent stays absent: a page shorter than :data:`MIN_TRANSCRIPT_CHARS` after cleaning is
treated as an episode page without a transcript, and a page without a publication time
is skipped, because an undated snapshot is not a collection record.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

from ..extraction.html import extract_visible_text
from ..models import CollectionProvenance, NormalizedRecord
from ..web_fetch import fetch_html_page
from .base import CollectionResult

# Below this, a "transcript" is a page template, not a conversation.
MIN_TRANSCRIPT_CHARS = 1500
# Same reasoning as the RSS cap: one page must not store a book, and when the cap
# bites the record says so.
MAX_TRANSCRIPT_CHARS = 400_000

_CHROME = re.compile(
    r"<(script|style|nav|header|footer|form|svg)\b[^>]*>.*?</\1\s*>", re.S | re.I
)
# A page's own <main>/<article> carries the transcript; the rest is site chrome. Measured
# on a real episode page, scoping to <main> removed the repeated footer menu the whole-page
# extraction kept ("… Privacy Terms Security Support Jobs About", twice).
_CONTENT_SCOPE = re.compile(r"<(main|article)\b[^>]*>(.*?)</\1\s*>", re.S | re.I)
_JSON_LD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I
)


def _json_ld_blobs(html: str) -> list[dict[str, Any]]:
    blobs: list[dict[str, Any]] = []
    for match in _JSON_LD.finditer(html):
        try:
            data = json.loads(match.group(1).strip())
        except (ValueError, TypeError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict):
                blobs.append(item)
                for key in ("@graph", "mainEntity", "itemListElement"):
                    nested = item.get(key)
                    if isinstance(nested, list):
                        blobs.extend(n for n in nested if isinstance(n, dict))
    return blobs


def _first_value(blobs: list[dict[str, Any]], *keys: str) -> str:
    for blob in blobs:
        for key in keys:
            value = blob.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict) and isinstance(value.get("name"), str):
                return value["name"].strip()
            if isinstance(value, list) and value and isinstance(value[0], dict):
                name = value[0].get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()
    return ""


def episode_metadata(html: str) -> dict[str, str]:
    """Title, author and publication time as the page itself declares them."""
    blobs = _json_ld_blobs(html)
    published = _first_value(blobs, "datePublished", "dateCreated", "uploadDate")
    return {
        "title": _first_value(blobs, "headline", "name"),
        "author": _first_value(blobs, "author", "creator", "publisher"),
        "published": published[:19],
    }


class PodcastTranscriptCollector:
    """One episode page in, one transcript record out."""

    def __init__(
        self,
        episode_url: str,
        *,
        fetch: Callable[[str], tuple[str, str] | None] = fetch_html_page,
    ) -> None:
        self.episode_url = episode_url
        self._fetch = fetch

    def collect(self) -> CollectionResult:
        result = CollectionResult()
        fetched = self._fetch(self.episode_url)
        if not fetched:
            result.warnings.append(f"episode_unreachable: {self.episode_url}")
            return result
        final_url, html = fetched

        meta = episode_metadata(html)
        if not meta["published"]:
            result.warnings.append(f"publication_time_missing: {final_url}")
            return result

        cleaned = _CHROME.sub(" ", html)
        scope = _CONTENT_SCOPE.search(cleaned)
        if scope:
            cleaned = scope.group(2)
        text = extract_visible_text(cleaned).text.strip()
        if len(text) < MIN_TRANSCRIPT_CHARS:
            result.warnings.append(
                f"transcript_unavailable: {final_url} ({len(text)} chars of page text)"
            )
            return result

        stored = text[:MAX_TRANSCRIPT_CHARS]
        result.records.append(
            NormalizedRecord(
                document_id=hashlib.sha256(final_url.encode("utf-8")).hexdigest(),
                platform="podcast",
                author=meta["author"],
                author_fullname=meta["author"],
                timestamp=meta["published"],
                source_url=final_url,
                text=stored,
                raw_payload={"title": meta["title"], "episode_url": final_url},
                raw_content_type="text/html",
                collection_provenance=CollectionProvenance(
                    module="podcast-transcript-html",
                    visited_url=final_url,
                    transformations=["page-chrome-strip", "visible-text", "podcast-transcript"],
                    metadata={
                        "episode_title": meta["title"],
                        "transcript_source": "page-html",
                        "text_chars": len(stored),
                        "text_truncated": len(text) > len(stored),
                        "audio_downloaded": False,
                    },
                ),
            )
        )
        result.raw_items_seen = 1
        return result
