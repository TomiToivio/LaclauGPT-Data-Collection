"""TikTok auxiliary capture parsers (comments, user details, hashtag details).

Recovered from the legacy 2024 LaclauGPT-TikTok-Scraper Firefox extension
(Firefox/background.js, CC0) — the archaeology source named in issue #2.
The newer collectors parsed posts only; comments, author profile statistics
and hashtag/challenge statistics were dropped in the rewrite. These are
useful public-API record families for research (comment-level discourse,
author-level follower context, hashtag reach), so the endpoint routing is
salvaged here and reshaped onto the canonical record envelope.

Each family emits NormalizedRecord rows with `platform="tiktok"` and a
record-type prefix in document_id so dedup keys never collide with posts:
- comments:  document_id = comment cid, parent_document_id = aweme_id
- users:     document_id = user id
- challenges (hashtag details): document_id = challenge id

Author: Tomi Toivio / LaclauGPT
License: CC0 1.0 Universal (legacy salvage, reshaped)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from ...models import CollectionProvenance, MediaReference, NormalizedRecord
from .common import as_string, first_value

KIND_COMMENT = "tiktok_comment"
KIND_USER = "tiktok_user"
KIND_CHALLENGE = "tiktok_challenge"


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except (TypeError, ValueError):
        return ""


def _provenance(metadata: dict[str, Any] | None, module: str) -> CollectionProvenance:
    metadata = metadata or {}
    return CollectionProvenance(
        captured_at=str(metadata.get("captured_at") or "") or CollectionProvenance().captured_at,
        capture_id=str(metadata.get("capture_id") or ""),
        run_id=str(metadata.get("run_id") or ""),
        module=module,
        module_version=module,
        git_commit=str(metadata.get("git_commit") or ""),
        visited_url=str(metadata.get("source_platform_url") or ""),
        api_url=str(metadata.get("source_url") or ""),
        transformations=["laclaugpt-network-capture", "legacy-salvage-map"],
    )


def _unix_to_iso(value: Any) -> tuple[str, int]:
    try:
        unix_ts = int(str(value))
    except (TypeError, ValueError):
        return "", 0
    if unix_ts <= 0:
        return "", unix_ts
    try:
        return datetime.fromtimestamp(unix_ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), unix_ts
    except (OverflowError, OSError, ValueError):
        return "", 0


def _comment_record(comment: dict, metadata: dict[str, Any] | None) -> NormalizedRecord | None:
    cid = as_string(comment.get("cid"))
    aweme_id = as_string(comment.get("aweme_id"))
    if not cid:
        return None
    user = comment.get("user") if isinstance(comment.get("user"), dict) else {}
    share = comment.get("share_info") if isinstance(comment.get("share_info"), dict) else {}
    timestamp, unix_ts = _unix_to_iso(comment.get("create_time"))
    digg = comment.get("digg_count")
    replies = comment.get("reply_comment_total")
    engagement: dict[str, Any] = {}
    if digg not in (None, ""):
        engagement["likes"] = digg
    if replies not in (None, ""):
        engagement["reply_count"] = replies
    return NormalizedRecord(
        schema_version="1.0",
        document_id=cid,
        platform=KIND_COMMENT,
        author=as_string(user.get("unique_id") or user.get("uid")),
        author_fullname=as_string(user.get("nickname")),
        timestamp=timestamp,
        unix_timestamp=unix_ts,
        source_url=as_string(share.get("url")),
        text=as_string(comment.get("text")),
        parent_document_id=aweme_id or None,
        engagement=engagement,
        collection_provenance=_provenance(metadata, "tiktok-comments-legacy-salvage"),
    )


def _user_record(user_info: dict, metadata: dict[str, Any] | None) -> NormalizedRecord | None:
    user = user_info.get("user") if isinstance(user_info.get("user"), dict) else {}
    stats = user_info.get("stats") if isinstance(user_info.get("stats"), dict) else {}
    uid = as_string(first_value(user.get("id"), user.get("uid"), user.get("uniqueId")))
    if not uid:
        return None
    engagement: dict[str, Any] = {}
    for key, source_key in (
        ("followers", "followerCount"),
        ("following", "followingCount"),
        ("friends", "friendCount"),
        ("hearts", "heart"),
        ("heart_count", "heartCount"),
        ("videos", "videoCount"),
        ("digg", "diggCount"),
    ):
        value = stats.get(source_key)
        if value not in (None, ""):
            engagement[key] = value
    avatar = as_string(user.get("avatarLarger"))
    return NormalizedRecord(
        schema_version="1.0",
        document_id=uid,
        platform=KIND_USER,
        author=as_string(user.get("uniqueId")),
        author_fullname=as_string(user.get("nickname")),
        source_url=f"https://www.tiktok.com/@{user.get('uniqueId', '')}" if user.get("uniqueId") else "",
        text=as_string(user.get("signature")),
        engagement=engagement,
        media_references=[MediaReference(kind="avatar", url=avatar, media_index=0)] if avatar.startswith("http") else [],
        collection_provenance=_provenance(metadata, "tiktok-users-legacy-salvage"),
    )


def _challenge_record(challenge_info: dict, metadata: dict[str, Any] | None) -> NormalizedRecord | None:
    challenge = challenge_info.get("challenge") if isinstance(challenge_info.get("challenge"), dict) else {}
    stats = challenge_info.get("statsV2") if isinstance(challenge_info.get("statsV2"), dict) else {}
    challenge_id = as_string(challenge.get("id"))
    if not challenge_id:
        return None
    engagement: dict[str, Any] = {}
    for key, source_key in (
        ("views", "viewCount"),
        ("videos", "videoCount"),
    ):
        value = stats.get(source_key)
        if value not in (None, ""):
            engagement[key] = value
    title = as_string(challenge.get("title"))
    return NormalizedRecord(
        schema_version="1.0",
        document_id=challenge_id,
        platform=KIND_CHALLENGE,
        author=title,
        source_url=f"https://www.tiktok.com/tag/{title}" if title else "",
        engagement=engagement,
        collection_provenance=_provenance(metadata, "tiktok-challenges-legacy-salvage"),
    )


def capture(response: Any, source_platform_url: str, source_url: str) -> list[dict]:
    """Route legacy endpoint payloads to native auxiliary objects.

    Comment lists return comment dicts; user/detail and challenge/detail
    return their wrapper dicts. Unknown payloads produce an empty list so
    the main post parser can still try the same body.
    """
    if _host(source_platform_url) != "tiktok.com":
        return []
    request_url = source_url or ""
    if isinstance(response, dict):
        data = response
    elif isinstance(response, str):
        try:
            import json
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            return []
    else:
        return []

    if "comment/list" in request_url:
        comments = data.get("comments")
        return [c for c in comments if isinstance(c, dict)] if isinstance(comments, list) else []
    if "user/detail" in request_url:
        return [data] if isinstance(data.get("userInfo"), dict) else []
    if "challenge/detail" in request_url:
        return [data] if isinstance(data.get("challengeInfo"), dict) else []
    return []


def map_item(item: dict, metadata: dict[str, Any] | None = None) -> dict:
    """Map one auxiliary object onto the shared mapped-record shape.

    The mapped dict carries `record_kind` so callers (normalize/ingest) can
    dispatch to the right envelope builder.
    """
    metadata = metadata or {}
    if "comments" in item or item.get("cid"):
        comment = item if item.get("cid") else {}
        return {"record_kind": "comment", "item": comment, "metadata": metadata}
    if item.get("userInfo"):
        return {"record_kind": "user", "item": item.get("userInfo"), "metadata": metadata}
    if item.get("challengeInfo"):
        return {"record_kind": "challenge", "item": item.get("challengeInfo"), "metadata": metadata}
    return {"record_kind": "unknown", "item": {}, "metadata": metadata}


def to_record(mapped: dict) -> NormalizedRecord | None:
    """Build the NormalizedRecord for one mapped auxiliary item."""
    kind = mapped.get("record_kind")
    item = mapped.get("item") or {}
    metadata = mapped.get("metadata")
    if kind == "comment":
        return _comment_record(item, metadata)
    if kind == "user":
        return _user_record(item, metadata)
    if kind == "challenge":
        return _challenge_record(item, metadata)
    return None