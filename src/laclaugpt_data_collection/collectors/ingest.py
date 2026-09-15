"""Convert one captured response body into normalized LaclauGPT records."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ..models import NormalizedRecord
from ..normalize import normalise
from .platforms import PARSERS


def platform_from_url(url: str) -> str | None:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "tiktok"
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "instagram"
    if host in {"x.com", "twitter.com"} or host.endswith(".x.com") or host.endswith(".twitter.com"):
        return "x"
    return None


def ingest_capture(
    *,
    response: Any,
    visited_url: str,
    response_url: str,
    metadata: dict[str, Any] | None = None,
    raw_ref: str = "",
) -> list[NormalizedRecord]:
    platform = platform_from_url(visited_url)
    if platform is None:
        return []
    parser = PARSERS[platform]
    merged_metadata = {
        **(metadata or {}),
        "source_platform_url": visited_url,
        "source_url": response_url,
    }
    records: list[NormalizedRecord] = []
    for raw_item in parser.capture(response, visited_url, response_url):
        mapped = parser.map_item(raw_item, merged_metadata)
        records.append(
            normalise(platform, mapped, metadata=merged_metadata, raw_ref=raw_ref)
        )
    return records
