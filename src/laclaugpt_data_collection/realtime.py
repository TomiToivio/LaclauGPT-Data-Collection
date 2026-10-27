"""Near-real-time collection-to-analysis scheduling helpers.

This module keeps policy decisions storage-neutral so local JSONL/SQLite polling and
remote MongoDB/Redis workers can implement the same observable semantics.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
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


#: Date formats that real feeds publish and that neither ISO 8601 nor RFC 2822 covers.
#: The etui feed (issue #295) emits a Drupal-rendered stamp: ``Tue, 10/20/2026 - 17:23``.
#: Python reports that as a ValueError from both parsers, so every etui record reached the
#: publication floor with no publication time and could never be dated.
#:
#: The ``m/d/Y`` order is the publisher's own convention (10/20/2026 can only be October 20th);
#: a feed using d/m/Y would be silently misread, so this list is deliberately explicit rather
#: than "some slash date" and a new publisher must be added here by name.
_SITE_DATE_FORMATS: tuple[str, ...] = (
    "%a, %m/%d/%Y - %H:%M",  # "Tue, 10/20/2026 - 17:23" (etui, Drupal)
    "%a, %m/%d/%Y %H:%M",
    "%m/%d/%Y - %H:%M",
    "%a, %d.%m.%Y - %H:%M",  # dotted European variant, day first, stated explicitly
    "%d.%m.%Y %H:%M",
    # "14 October 2026" -- the European Commission's digital-strategy pages render
    # their date as ``<time datetime="14 October 2026">``, which ``web_fetch`` picks
    # up and hands to this parser (#362). The month is spelled, so day-first and
    # month-first cannot be confused; ``%d`` accepts both "05" and "5".
    "%d %B %Y",
)


def _parse_site_datetime(text: str) -> datetime | None:
    """Parse a publisher-specific stamp from ``_SITE_DATE_FORMATS``; None when none matches."""
    cleaned = " ".join(text.replace("\u2013", "-").replace("\u2014", "-").split())
    for fmt in _SITE_DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None

def parse_source_time(value: object) -> datetime | None:
    """Parse ISO or RFC/RSS source time without substituting collection time."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            dt = datetime.fromisoformat(iso_text)
        except ValueError:
            try:
                dt = parsedate_to_datetime(text)
            except (TypeError, ValueError, OverflowError):
                # A publisher stamp that neither parser recognises is not automatically a
                # missing date: the etui feed's Drupal stamp is a real publication time
                # (issue #295). Try the named formats before giving up.
                dt = _parse_site_datetime(text)
                if dt is None:
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


def _source_mapping(record: Any) -> Mapping[str, Any]:
    """Read the ``source`` section from a canonical model or a plain mapping."""
    if isinstance(record, Mapping):
        source = record.get("source")
    else:
        source = getattr(record, "source", None)
    if isinstance(source, Mapping):
        return source
    dumped = getattr(source, "model_dump", None)
    if not callable(dumped):
        return {}
    payload = dumped()
    return payload if isinstance(payload, Mapping) else {}


def unparsed_source_time_counts(records: Iterable[Any]) -> dict[str, int]:
    """Count records whose source time string no parser accepts, keyed by source.

    #295: a rejected source time is stored as ``handoff.published_at = null``, and
    the study requires a source publication time for analysis, so such a row can
    never be analysed. Losing the time silently converts fetchable content into
    permanently unusable rows, so the failure is counted here and reported by the
    collection cycle instead of being swallowed.

    Parsing a publisher stamp (#295) and *noticing* an unparsed one are separate
    duties: the next publisher whose format is unknown must not be able to re-open
    the silent-ineligibility path this issue describes.
    """
    counts: dict[str, int] = {}
    for record in records:
        source = _source_mapping(record)
        raw = str(source.get("created_at") or "").strip()
        if not raw or parse_source_time(raw) is not None:
            continue
        metadata = source.get("raw_metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        name = str(metadata.get("source_name") or source.get("platform") or "unnamed")
        counts[name] = counts.get(name, 0) + 1
    return counts


def unparsed_source_time_warning(records: Iterable[Any]) -> str | None:
    """Return one counted, source-naming warning for unparseable source times."""
    counts = unparsed_source_time_counts(records)
    if not counts:
        return None
    total = sum(counts.values())
    detail = ", ".join(
        f"{name}={count}"
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )
    return (
        f"{total} record(s) with unparseable source publication time "
        f"(stored with handoff.published_at=null and therefore unanalysable): {detail}"
    )


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
