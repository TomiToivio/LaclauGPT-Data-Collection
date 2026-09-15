"""Compact LaclauGPT-native X/Twitter parser.

Adapted from the public collector's X parser. IDs are always strings because
platform snowflake IDs exceed JavaScript's exact integer range.
"""
from __future__ import annotations

import json
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

from .common import as_string, first_value, unique

_DOMAINS = {"x.com", "twitter.com"}


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except (TypeError, ValueError):
        return ""


def _tweet_candidates(node: Any) -> list[dict]:
    found: list[dict] = []
    if isinstance(node, list):
        for child in node:
            found.extend(_tweet_candidates(child))
    elif isinstance(node, dict):
        legacy = node.get("legacy")
        rest_id = first_value(node.get("rest_id"), node.get("id_str"), node.get("tweet_id"))
        if isinstance(legacy, dict) and rest_id and (
            legacy.get("full_text") is not None or legacy.get("text") is not None
        ):
            copied = dict(node)
            copied["_laclaugpt_rest_id"] = as_string(rest_id)
            found.append(copied)
        elif rest_id and (node.get("full_text") is not None or node.get("text") is not None):
            found.append(node)
        else:
            for key, value in node.items():
                if key not in {"user_results", "quoted_status_result"}:
                    found.extend(_tweet_candidates(value))
    return found


def capture(response: Any, source_platform_url: str, source_url: str) -> list[dict]:
    del source_url
    if _host(source_platform_url) not in _DOMAINS:
        return []
    if isinstance(response, dict):
        data = response
    elif isinstance(response, str):
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            return []
    else:
        return []
    dedup: dict[str, dict] = {}
    for item in _tweet_candidates(data):
        legacy = item.get("legacy") if isinstance(item.get("legacy"), dict) else item
        item_id = as_string(first_value(item.get("_laclaugpt_rest_id"), item.get("rest_id"), legacy.get("id_str")))
        if item_id:
            dedup[item_id] = item
    return list(dedup.values())


def _user(item: dict) -> dict:
    core = item.get("core") if isinstance(item.get("core"), dict) else {}
    result = core.get("user_results") if isinstance(core.get("user_results"), dict) else {}
    user = result.get("result") if isinstance(result.get("result"), dict) else {}
    legacy = user.get("legacy") if isinstance(user.get("legacy"), dict) else {}
    return {**legacy, **{k: v for k, v in user.items() if k != "legacy"}}


def _timestamp(value: Any) -> tuple[str, int]:
    if not value:
        return "", 0
    try:
        dt = parsedate_to_datetime(str(value))
        return dt.isoformat().replace("+00:00", "Z"), int(dt.timestamp())
    except (TypeError, ValueError, OverflowError):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt.isoformat().replace("+00:00", "Z"), int(dt.timestamp())
        except ValueError:
            return "", 0


def map_item(item: dict, metadata: dict | None = None) -> dict:
    metadata = metadata or {}
    legacy = item.get("legacy") if isinstance(item.get("legacy"), dict) else item
    item_id = as_string(first_value(item.get("_laclaugpt_rest_id"), item.get("rest_id"), legacy.get("id_str")))
    user = _user(item)
    username = as_string(first_value(user.get("screen_name"), user.get("legacy", {}).get("screen_name") if isinstance(user.get("legacy"), dict) else None))
    text = as_string(first_value(legacy.get("full_text"), legacy.get("text")))
    stamp, unix_ts = _timestamp(first_value(legacy.get("created_at"), item.get("created_at")))
    entities = legacy.get("entities") if isinstance(legacy.get("entities"), dict) else {}
    hashtags = unique(
        as_string(row.get("text"))
        for row in entities.get("hashtags") or []
        if isinstance(row, dict)
    )
    mentions = unique(
        as_string(row.get("screen_name"))
        for row in entities.get("user_mentions") or []
        if isinstance(row, dict)
    )
    extended = legacy.get("extended_entities") if isinstance(legacy.get("extended_entities"), dict) else {}
    images: list[str] = []
    videos: list[str] = []
    for media in extended.get("media") or []:
        if not isinstance(media, dict):
            continue
        if media.get("media_url_https"):
            images.append(as_string(media["media_url_https"]))
        info = media.get("video_info") if isinstance(media.get("video_info"), dict) else {}
        variants = [v for v in info.get("variants") or [] if isinstance(v, dict) and v.get("url")]
        mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
        if mp4s:
            best = max(mp4s, key=lambda v: int(v.get("bitrate") or 0))
            videos.append(as_string(best.get("url")))
    thread_id = as_string(first_value(legacy.get("conversation_id_str"), item_id))
    is_reply = "yes" if legacy.get("in_reply_to_status_id_str") else "no"
    link = f"https://x.com/{username}/status/{item_id}" if username else f"https://x.com/i/status/{item_id}"
    return {
        "collected_from_url": metadata.get("source_platform_url", ""),
        "id": item_id,
        "thread_id": thread_id,
        "is_reply": is_reply,
        "author": username,
        "author_full": as_string(user.get("name")),
        "author_followers": user.get("followers_count"),
        "body": text,
        "timestamp": stamp,
        "unix_timestamp": unix_ts,
        "link": link,
        "hashtags": ",".join(hashtags),
        "mentions": ",".join(mentions),
        "images": ",".join(unique(images)),
        "videos": ",".join(unique(videos)),
        "like_count": legacy.get("favorite_count"),
        "retweet_count": legacy.get("retweet_count"),
        "reply_count": legacy.get("reply_count"),
        "quote_count": legacy.get("quote_count"),
        "language_guess": as_string(legacy.get("lang")),
    }
