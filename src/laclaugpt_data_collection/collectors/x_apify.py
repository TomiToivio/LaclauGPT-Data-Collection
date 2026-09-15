"""Optional X/Twitter acquisition via Apify.

The existing browser/platform parser remains the default public path. This adapter
only adds provider-based acquisition and maps payloads into the same canonical model.
"""
from __future__ import annotations

from typing import Any

from ..models import CollectionProvenance, MediaReference, NormalizedRecord
from .base import CollectionResult


def map_apify_item(item: dict[str, Any], *, handle: str = "") -> NormalizedRecord | None:
    source_url = str(item.get("url") or "")
    if not source_url:
        return None
    tweet_id = str(item.get("id") or source_url.rsplit("/", 1)[-1])
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    username = str(author.get("userName") or author.get("username") or handle)
    media: list[MediaReference] = []
    extended = item.get("extendedEntities") if isinstance(item.get("extendedEntities"), dict) else {}
    for index, entry in enumerate(extended.get("media") or []):
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("media_url_https") or entry.get("url") or "")
        if url:
            media.append(MediaReference(kind=str(entry.get("type") or "media"), url=url, media_index=index))
    return NormalizedRecord(
        document_id=tweet_id,
        platform="x",
        author=username,
        author_fullname=str(author.get("name") or ""),
        timestamp=str(item.get("createdAt") or item.get("created_at") or ""),
        source_url=source_url,
        text=str(item.get("text") or ""),
        language=str(item.get("lang") or ""),
        engagement={
            "like_count": item.get("likeCount") or item.get("like_count"),
            "retweet_count": item.get("retweetCount") or item.get("retweet_count"),
            "reply_count": item.get("replyCount") or item.get("reply_count"),
            "quote_count": item.get("quoteCount") or item.get("quote_count"),
        },
        media_references=media,
        collection_provenance=CollectionProvenance(
            module="apify-x",
            visited_url=source_url,
            transformations=["apify-dataset", "map-x-item"],
            metadata={"provider": "apify", "raw_item": item},
        ),
    )


class XApifyCollector:
    def __init__(self, accounts: list[str], *, token: str, max_items: int = 100, actor_id: str = "nfp1fpt5gUlBwPcor", client: Any | None = None) -> None:
        self.accounts = [account.lstrip("@") for account in accounts]
        self.token = token
        self.max_items = max_items
        self.actor_id = actor_id
        self.client = client

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        try:
            from apify_client import ApifyClient
        except ImportError as exc:
            raise RuntimeError("Install the 'x-apify' extra for Apify acquisition") from exc
        return ApifyClient(self.token)

    def collect(self) -> CollectionResult:
        result = CollectionResult()
        client = self._client()
        for handle in self.accounts:
            result.requests_seen += 1
            run = client.actor(self.actor_id).call(run_input={"includeSearchTerms": False, "maxItems": self.max_items, "sort": "Latest", "twitterHandles": [handle]})
            rows = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            result.bodies_seen += 1
            result.raw_items_seen += len(rows)
            for row in rows:
                record = map_apify_item(dict(row), handle=handle)
                if record:
                    result.records.append(record)
        if not result.records:
            result.warnings.append(result.zero_result_warning or "No X items collected")
        return result
