"""Convert one captured response body into normalized LaclauGPT records.

Extended with the legacy-salvaged auxiliary families: when the response URL
matches a TikTok comment/user/challenge endpoint, records are emitted through
the aux path with distinct platform-kind values.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ..models import NormalizedRecord
from ..normalize import normalise, normalise_aux
from .platforms import PARSERS, tiktok_extras

# Response-URL fragments that identify auxiliary capture families.
_AUX_ENDPOINTS = ("comment/list", "user/detail", "challenge/detail")


def platform_from_url(url: str) -> str | None:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "tiktok"
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "instagram"
    if host in {"x.com", "twitter.com"} or host.endswith(".x.com") or host.endswith(".twitter.com"):
        return "x"
    return None


def _aux_kind_from_url(response_url: str) -> str | None:
    url = response_url or ""
    if "comment/list" in url:
        return "tiktok_comment"
    if "user/detail" in url:
        return "tiktok_user"
    if "challenge/detail" in url:
        return "tiktok_challenge"
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
    merged_metadata = {
        **(metadata or {}),
        "source_platform_url": visited_url,
        "source_url": response_url,
    }

    # Auxiliary families route by response-URL fragment first: a comment list
    # never flows through the post parser, and post endpoints never flow
    # through the aux parser.
    aux_kind = _aux_kind_from_url(response_url) if platform == "tiktok" else None
    if aux_kind is not None:
        records: list[NormalizedRecord] = []
        for raw_item in tiktok_extras.capture(response, visited_url, response_url):
            mapped = tiktok_extras.map_item(raw_item, merged_metadata)
            # The aux kind implied by the response URL is authoritative; skip
            # items whose own shape does not match it (never guess silently).
            item_kind = mapped.get("record_kind")
            expected = aux_kind.removeprefix("tiktok_")
            if item_kind not in (None, "unknown", expected):
                continue
            mapped["record_kind"] = expected
            try:
                records.append(normalise_aux(aux_kind, mapped, raw_ref=raw_ref))
            except ValueError:
                continue
        return records

    parser = PARSERS[platform]
    records = []
    for raw_item in parser.capture(response, visited_url, response_url):
        mapped = parser.map_item(raw_item, merged_metadata)
        records.append(
            normalise(platform, mapped, metadata=merged_metadata, raw_ref=raw_ref)
        )
    return records