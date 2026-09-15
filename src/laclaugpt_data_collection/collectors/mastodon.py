"""Mastodon collection using public/authenticated Mastodon APIs.

Reimplemented from CyborgAnthropology without storage coupling or embedded targets.
"""
from __future__ import annotations

import re
from html import unescape
from typing import Any

from ..models import CollectionProvenance, MediaReference, NormalizedRecord
from .base import CollectionResult

_TAG_RE = re.compile(r"<[^>]+>")


def map_status(status: dict[str, Any], *, instance_url: str) -> NormalizedRecord | None:
    status_id = str(status.get("id") or "")
    account = status.get("account") if isinstance(status.get("account"), dict) else {}
    username = str(account.get("acct") or account.get("username") or "")
    source_url = str(status.get("url") or "")
    if not source_url and status_id and username:
        source_url = f"{instance_url.rstrip('/')}/@{username.split('@', 1)[0]}/{status_id}"
    if not source_url:
        return None
    html = str(status.get("content") or "")
    text = unescape(_TAG_RE.sub(" ", html))
    text = " ".join(text.split())
    media = []
    for index, item in enumerate(status.get("media_attachments") or []):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("remote_url") or item.get("preview_url") or "")
        if url:
            media.append(MediaReference(kind=str(item.get("type") or "media"), url=url, media_index=index, metadata={"description": item.get("description")}))
    return NormalizedRecord(
        document_id=status_id or source_url,
        platform="mastodon",
        author=username,
        author_fullname=str(account.get("display_name") or ""),
        timestamp=str(status.get("created_at") or ""),
        source_url=source_url,
        text=text,
        language=str(status.get("language") or ""),
        engagement={
            "favourites_count": status.get("favourites_count"),
            "reblogs_count": status.get("reblogs_count"),
            "replies_count": status.get("replies_count"),
        },
        media_references=media,
        collection_provenance=CollectionProvenance(
            module="mastodon-api",
            visited_url=source_url,
            api_url=instance_url,
            transformations=["mastodon-api", "html-to-text", "map-status"],
            metadata={"account_url": account.get("url")},
        ),
    )


class MastodonCollector:
    def __init__(self, instance_url: str, *, hashtag: str | None = None, limit: int = 20, access_token: str | None = None, client: Any | None = None) -> None:
        self.instance_url = instance_url.rstrip("/")
        self.hashtag = hashtag.lstrip("#") if hashtag else None
        self.limit = limit
        self.access_token = access_token
        self.client = client

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        try:
            from mastodon import Mastodon
        except ImportError as exc:
            raise RuntimeError("Install the 'mastodon' extra to collect from Mastodon") from exc
        return Mastodon(api_base_url=self.instance_url, access_token=self.access_token)

    def collect(self) -> CollectionResult:
        result = CollectionResult(requests_seen=1)
        client = self._client()
        rows = client.timeline_hashtag(self.hashtag, limit=self.limit) if self.hashtag else client.timeline_public(limit=self.limit)
        result.bodies_seen = 1
        result.raw_items_seen = len(rows)
        for row in rows:
            record = map_status(dict(row), instance_url=self.instance_url)
            if record:
                result.records.append(record)
        if not result.records:
            result.warnings.append(result.zero_result_warning or "No Mastodon statuses collected")
        return result
