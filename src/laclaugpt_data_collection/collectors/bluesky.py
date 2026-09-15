"""Public Bluesky/XRPC collector.

Based on the reusable public-API collector pattern in LaclauGPT-Discourse-Analysis.
Targets are supplied at runtime and are never embedded in source code.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import CollectionProvenance, NormalizedRecord
from .base import CollectionResult

PUBLIC_API = "https://public.api.bsky.app/xrpc"


class BlueskyCollector:
    def __init__(
        self,
        *,
        query: str | None = None,
        actor: str | None = None,
        max_results: int = 100,
        access_token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        if bool(query) == bool(actor):
            raise ValueError("Provide exactly one of query or actor")
        self.query = query
        self.actor = actor
        self.max_results = max_results
        self.access_token = access_token
        self.timeout = timeout

    def collect(self) -> CollectionResult:
        result = CollectionResult()
        cursor: str | None = None
        while len(result.records) < self.max_results:
            limit = min(100, self.max_results - len(result.records))
            if self.query:
                endpoint = f"{PUBLIC_API}/app.bsky.feed.searchPosts"
                params: dict[str, Any] = {"q": self.query, "limit": limit}
            else:
                endpoint = f"{PUBLIC_API}/app.bsky.feed.getAuthorFeed"
                params = {"actor": self.actor, "limit": limit, "filter": "posts_with_replies"}
            if cursor:
                params["cursor"] = cursor
            headers = {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}
            result.requests_seen += 1
            response = httpx.get(endpoint, params=params, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            result.bodies_seen += 1
            rows = payload.get("posts") if self.query else payload.get("feed")
            if not isinstance(rows, list):
                rows = []
            result.raw_items_seen += len(rows)
            for row in rows:
                record = _map_search_post(row) if self.query else _map_feed_item(row)
                if record:
                    result.records.append(record)
                    if len(result.records) >= self.max_results:
                        break
            cursor = payload.get("cursor")
            if not cursor or not rows:
                break
        warning = result.zero_result_warning
        if warning and not result.records:
            result.warnings.append(warning)
        return result


def _map_feed_item(row: Any) -> NormalizedRecord | None:
    if not isinstance(row, dict):
        return None
    post = row.get("post")
    return _map_post(post, raw_payload=row) if isinstance(post, dict) else None


def _map_search_post(post: Any) -> NormalizedRecord | None:
    return _map_post(post, raw_payload=post) if isinstance(post, dict) else None


def _map_post(post: dict[str, Any], *, raw_payload: Any | None = None) -> NormalizedRecord | None:
    uri = str(post.get("uri") or "")
    if not uri:
        return None
    cid = str(post.get("cid") or "")
    record = post.get("record") if isinstance(post.get("record"), dict) else {}
    author = post.get("author") if isinstance(post.get("author"), dict) else {}
    if not isinstance(record, dict):
        record = {}
    if not isinstance(author, dict):
        author = {}
    text = str(record.get("text") or "")
    created_at = str(record.get("createdAt") or "")
    handle = str(author.get("handle") or "")
    rkey = uri.rsplit("/", 1)[-1]
    source_url = f"https://bsky.app/profile/{handle}/post/{rkey}" if handle else ""
    indexed_at = str(post.get("indexedAt") or datetime.now(timezone.utc).isoformat())
    return NormalizedRecord(
        document_id=cid or uri,
        platform="bluesky",
        author=handle,
        author_fullname=str(author.get("displayName") or ""),
        timestamp=created_at,
        source_url=source_url,
        text=text,
        language=(record.get("langs") or [""])[0] if isinstance(record.get("langs"), list) else "",
        engagement={
            "like_count": post.get("likeCount"),
            "reply_count": post.get("replyCount"),
            "repost_count": post.get("repostCount"),
            "quote_count": post.get("quoteCount"),
        },
        raw_payload=raw_payload if raw_payload is not None else post,
        raw_content_type="application/json",
        collection_provenance=CollectionProvenance(
            captured_at=indexed_at,
            module="laclaugpt-native-bluesky-2026-09",
            visited_url=source_url,
            api_url=uri,
            transformations=["bsky-xrpc", "map-post"],
            metadata={"raw_item": post},
        ),
    )
