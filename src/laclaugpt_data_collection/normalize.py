"""Normalize parser output into the stable LaclauGPT record envelope.

Adapted from the public `collector/normalize.py` in
TomiToivio/LaclauGPT-Discourse-Analysis.
"""
from __future__ import annotations

from typing import Any

from .models import CollectionProvenance, MediaReference, NormalizedRecord

MODULE_VERSIONS = {
    "tiktok": "laclaugpt-native-tiktok-2026-09",
    "instagram": "laclaugpt-native-instagram-2026-09",
    "x": "laclaugpt-native-twitter-2026-09",
    "bluesky": "laclaugpt-native-bluesky-2026-09",
}


def normalise(
    platform: str,
    mapped: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
    raw_ref: str = "",
) -> NormalizedRecord:
    metadata = metadata or {}
    document_id = str(mapped.get("id") or "")
    if not document_id:
        raise ValueError("normalise: mapped record without id")

    source_url = str(
        mapped.get("link")
        or mapped.get("tiktok_url")
        or mapped.get("url")
        or mapped.get("collected_from_url")
        or ""
    )

    parent: str | None = None
    if platform == "x":
        thread = str(mapped.get("thread_id") or "")
        if mapped.get("is_reply") == "yes" and thread and thread != document_id:
            parent = thread
    elif platform == "instagram":
        parent_value = mapped.get("parent_id")
        parent = str(parent_value) if parent_value else None

    engagement_keys = (
        "likes",
        "comments",
        "shares",
        "plays",
        "like_count",
        "comment_count",
        "retweet_count",
        "quote_count",
        "reply_count",
        "impression_count",
        "play_count",
        "num_likes",
        "num_comments",
        "author_followers",
    )
    engagement = {
        key: mapped[key]
        for key in engagement_keys
        if mapped.get(key) not in (None, "", -1)
    }

    provenance = CollectionProvenance(
        captured_at=str(metadata.get("captured_at") or "")
        or CollectionProvenance().captured_at,
        capture_id=str(metadata.get("capture_id") or ""),
        run_id=str(metadata.get("run_id") or ""),
        module=MODULE_VERSIONS.get(platform, platform),
        module_version=MODULE_VERSIONS.get(platform, ""),
        git_commit=str(metadata.get("git_commit") or ""),
        visited_url=str(metadata.get("source_platform_url") or ""),
        api_url=str(metadata.get("source_url") or ""),
        transformations=["laclaugpt-network-capture", "map-item-normalise"],
    )

    return NormalizedRecord(
        document_id=document_id,
        platform=platform,
        author=str(mapped.get("author") or ""),
        author_fullname=str(mapped.get("author_full") or mapped.get("author_fullname") or ""),
        timestamp=str(mapped.get("timestamp") or ""),
        unix_timestamp=int(mapped.get("unix_timestamp") or 0),
        source_url=source_url,
        text=str(mapped.get("body") or ""),
        language=str(mapped.get("language_guess") or "") if platform == "x" else "",
        parent_document_id=parent,
        hashtags=_split_list(mapped.get("hashtags")),
        mentions=_split_list(mapped.get("mentions")),
        engagement=engagement,
        media_references=_media_refs(platform, mapped),
        raw_ref=raw_ref,
        collection_provenance=provenance,
    )


def _split_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if not value:
        return []
    return [item for item in str(value).split(",") if item]


def _media_refs(platform: str, mapped: dict[str, Any]) -> list[MediaReference]:
    refs: list[MediaReference] = []

    def add(kind: str, url: Any, index: int) -> None:
        if isinstance(url, str) and url.startswith("http"):
            refs.append(MediaReference(kind=kind, url=url, media_index=index))

    if platform == "tiktok":
        add("video", mapped.get("video_url"), 0)
        add("thumbnail", mapped.get("thumbnail_url"), 1)
    elif platform == "instagram":
        for index, url in enumerate(_split_list(mapped.get("media_urls"))):
            add("video" if mapped.get("media_type") == "video" else "image", url, index)
        for index, url in enumerate(_split_list(mapped.get("image_urls"))):
            add("image", url, 100 + index)
    elif platform == "x":
        for index, url in enumerate(_split_list(mapped.get("videos"))):
            add("video", url, index)
        for index, url in enumerate(_split_list(mapped.get("images"))):
            add("image", url, 10 + index)
        for index, url in enumerate(_split_list(mapped.get("quote_videos"))):
            add("quote_video", url, 20 + index)
        for index, url in enumerate(_split_list(mapped.get("quote_images"))):
            add("quote_image", url, 30 + index)
    return refs
