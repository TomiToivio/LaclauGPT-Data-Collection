"""Near-real-time collection-to-analysis scheduling helpers.

This module keeps policy decisions storage-neutral so local JSONL/SQLite polling and
remote MongoDB/Redis workers can implement the same observable semantics.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from .models import canonicalize_source_url

_URL_RE = re.compile(r"https?://[^\s<>\]\[(){}\"']+")
_X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "t.co"}


@dataclass(frozen=True)
class RealtimePolicy:
    """Portable handoff policy shared by cron, SQLite, MongoDB and Redis modes."""

    publication_date_floor: datetime | None = None
    source_priorities: dict[str, int] = field(default_factory=dict)
    default_priority: int = 2

    @classmethod
    def ai26(cls) -> "RealtimePolicy":
        return cls(
            publication_date_floor=datetime(2026, 9, 1, tzinfo=UTC),
            source_priorities={
                "web": 1,
                "rss": 1,
                "document": 1,
                "pdf": 1,
                "scholarly": 1,
                "parliamentary": 1,
                "youtube": 1,
                "tiktok": 2,
                "instagram": 2,
                "bluesky": 2,
                "mastodon": 2,
                "x": 3,
                "twitter": 3,
            },
        )


def parse_source_time(value: object) -> datetime | None:
    """Parse a source publication timestamp without substituting collection time."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def source_family(record: dict) -> str:
    source = record.get("source") or {}
    raw = str(
        record.get("source_family")
        or record.get("platform")
        or source.get("source_type")
        or source.get("platform")
        or "web"
    ).strip().lower()
    aliases = {"tweet": "x", "twitter/x": "x", "webpage": "web", "html": "web"}
    return aliases.get(raw, raw)


def source_publication_time(record: dict) -> datetime | None:
    """Read canonical source publication time only.

    Collection/fetch timestamps are intentionally excluded: missing source time must
    remain explicit rather than being silently replaced by collection time.
    """
    source = record.get("source") or {}
    for value in (
        record.get("published_at"),
        record.get("source_publication_time"),
        source.get("published_at"),
        source.get("created_at"),
    ):
        parsed = parse_source_time(value)
        if parsed is not None:
            return parsed
    return None


def analysis_eligibility(record: dict, policy: RealtimePolicy) -> tuple[bool, str]:
    published = source_publication_time(record)
    if published is None:
        return False, "missing_source_publication_time"
    if policy.publication_date_floor and published < policy.publication_date_floor:
        return False, "before_publication_date_floor"
    return True, "eligible"


def source_priority(record: dict, policy: RealtimePolicy) -> int:
    explicit = record.get("source_priority")
    if explicit is not None:
        try:
            return int(explicit)
        except (TypeError, ValueError):
            pass
    return policy.source_priorities.get(source_family(record), policy.default_priority)


def scheduling_key(record: dict, policy: RealtimePolicy) -> tuple[int, float, str]:
    """Return ``(priority ASC, published_at DESC, source_id ASC)`` sort key."""
    published = source_publication_time(record)
    timestamp = published.timestamp() if published else float("-inf")
    source_id = str(record.get("source_url") or record.get("document_id") or "")
    return source_priority(record, policy), -timestamp, source_id


def prepare_analysis_candidates(records: Iterable[dict], policy: RealtimePolicy) -> list[dict]:
    """Filter and order analysis candidates deterministically.

    Returned records are shallow copies with portable scheduling metadata. Raw input is
    left untouched so provenance remains reproducible.
    """
    candidates: list[dict] = []
    for record in records:
        eligible, reason = analysis_eligibility(record, policy)
        if not eligible:
            continue
        item = dict(record)
        item["source_priority"] = source_priority(record, policy)
        item["analysis_readiness"] = reason
        published = source_publication_time(record)
        item["published_at"] = published.isoformat() if published else None
        candidates.append(item)
    candidates.sort(key=lambda item: scheduling_key(item, policy))
    return candidates


def mark_realtime_metadata(record: dict, *, collection_id: str = "ai26", arena: str | None = None) -> dict:
    """Attach shared dataset metadata without splitting arenas into separate datasets."""
    item = dict(record)
    item["collection_id"] = collection_id
    if arena:
        item["arena"] = arena
    return item


def extract_external_urls(text: str, *, originating_url: str | None = None) -> list[str]:
    """Extract canonical external HTTP(S) links, ignoring X/Twitter navigation links."""
    origin_host = urlsplit(originating_url).netloc.lower() if originating_url else ""
    found: list[str] = []
    seen: set[str] = set()
    for match in _URL_RE.findall(text or ""):
        candidate = match.rstrip(".,;:!?")
        canonical = canonicalize_source_url(candidate)
        host = urlsplit(canonical).netloc.lower()
        if not host or host in _X_HOSTS or (origin_host and host == origin_host):
            continue
        if canonical not in seen:
            seen.add(canonical)
            found.append(canonical)
    return found


def web_child_record(url: str, parent: dict, *, title: str | None = None) -> dict:
    """Create a canonical WEB child-source envelope with parent provenance.

    Fetching/extraction stays in the web collector. Failure to fetch this child must not
    mutate or invalidate the parent record.
    """
    parent_url = str(parent.get("source_url") or "")
    collection_id = str(parent.get("collection_id") or "ai26")
    child = {
        "source_url": canonicalize_source_url(url),
        "collection_id": collection_id,
        "source": {
            "platform": "web",
            "source_type": "WEB",
            "parent_source_url": parent_url or None,
        },
        "content": {"text": "", "title": title},
        "discovered_via": parent_url or None,
    }
    if parent.get("arena"):
        child["arena"] = parent["arena"]
    return child
