"""Compact LaclauGPT-native Instagram parser.

Adapted from the richer public parser in LaclauGPT-Discourse-Analysis. This
keeps the reusable post/reel extraction boundary without project-specific code.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .common import as_string, first_value, unique

DOMAIN = "instagram.com"
_HASHTAG_RE = re.compile(r"#([\wÀ-ÖØ-öø-ÿ]+)", re.UNICODE)


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except (TypeError, ValueError):
        return ""


def _looks_like_media(item: Any) -> bool:
    return isinstance(item, dict) and bool(
        first_value(item.get("pk"), item.get("id"), item.get("code"), item.get("shortcode"))
    ) and bool(
        item.get("media_type")
        or item.get("code")
        or item.get("shortcode")
        or item.get("image_versions2")
        or item.get("video_versions")
        or item.get("display_url")
        or item.get("edge_media_to_caption")
    )


def _walk(node: Any) -> list[dict]:
    found: list[dict] = []
    if isinstance(node, list):
        for child in node:
            found.extend(_walk(child))
    elif isinstance(node, dict):
        if _looks_like_media(node):
            found.append(node)
        else:
            for key, value in node.items():
                if key not in {"user", "owner", "caption", "image_versions2", "video_versions"}:
                    found.extend(_walk(value))
    return found


def capture(response: Any, source_platform_url: str, source_url: str) -> list[dict]:
    del source_url
    if _host(source_platform_url) != DOMAIN:
        return []
    if isinstance(response, dict):
        data = response
    elif isinstance(response, str):
        body = response.strip().removeprefix("for (;;);")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return []
    else:
        return []

    dedup: dict[str, dict] = {}
    for item in _walk(data):
        item_id = as_string(first_value(item.get("pk"), item.get("id"), item.get("code"), item.get("shortcode")))
        if item_id:
            dedup[item_id] = item
    return list(dedup.values())


def _caption(item: dict) -> str:
    caption = item.get("caption")
    if isinstance(caption, str):
        return caption
    if isinstance(caption, dict):
        return as_string(caption.get("text"))
    try:
        return as_string(item["edge_media_to_caption"]["edges"][0]["node"]["text"])
    except (KeyError, IndexError, TypeError):
        return ""


def _timestamp(item: dict) -> tuple[str, int]:
    value = first_value(item.get("taken_at"), item.get("taken_at_timestamp"), item.get("created_time"))
    try:
        unix_ts = int(str(value))
        stamp = datetime.fromtimestamp(unix_ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return stamp, unix_ts
    except (TypeError, ValueError, OverflowError, OSError):
        return "", 0


def _urls(item: dict, key: str) -> list[str]:
    out: list[str] = []
    if key == "image":
        for field in ("display_url", "display_uri", "display_src"):
            if item.get(field):
                out.append(as_string(item[field]))
        image_versions = item.get("image_versions2") or {}
        if isinstance(image_versions, dict):
            for candidate in image_versions.get("candidates") or []:
                if isinstance(candidate, dict) and candidate.get("url"):
                    out.append(as_string(candidate["url"]))
    else:
        if item.get("video_url"):
            out.append(as_string(item["video_url"]))
        for version in item.get("video_versions") or []:
            if isinstance(version, dict) and version.get("url"):
                out.append(as_string(version["url"]))
    return unique(out)


def map_item(item: dict, metadata: dict | None = None) -> dict:
    metadata = metadata or {}
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    author = {**owner, **user}
    shortcode = as_string(first_value(item.get("code"), item.get("shortcode")))
    native_id = as_string(first_value(item.get("pk"), item.get("id"), shortcode))
    record_id = shortcode or native_id
    text = _caption(item)
    stamp, unix_ts = _timestamp(item)
    video_urls = _urls(item, "video")
    image_urls = _urls(item, "image")
    is_video = bool(video_urls or item.get("media_type") == 2 or item.get("is_video"))
    route = "reel" if is_video else "p"
    url = f"https://www.instagram.com/{route}/{shortcode}" if shortcode else ""
    return {
        "collected_from_url": metadata.get("source_platform_url", ""),
        "id": record_id,
        "author": as_string(first_value(author.get("username"), item.get("owner_username"))),
        "author_full": as_string(first_value(author.get("full_name"), author.get("name"))),
        "body": text,
        "timestamp": stamp,
        "unix_timestamp": unix_ts,
        "url": url,
        "media_type": "video" if is_video else "photo",
        "media_urls": ",".join(video_urls),
        "image_urls": ",".join(image_urls),
        "hashtags": ",".join(unique(match.group(1) for match in _HASHTAG_RE.finditer(text))),
        "like_count": first_value(item.get("like_count"), (item.get("edge_media_preview_like") or {}).get("count")),
        "comment_count": first_value(item.get("comment_count"), (item.get("edge_media_to_comment") or {}).get("count")),
        "play_count": first_value(item.get("play_count"), item.get("view_count"), item.get("video_view_count")),
    }
