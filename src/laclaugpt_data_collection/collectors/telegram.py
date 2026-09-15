"""Telegram/Telethon adapter with credentials and sessions supplied externally."""
from __future__ import annotations

from typing import Any

from ..models import CollectionProvenance, MediaReference, NormalizedRecord
from .base import CollectionResult


def map_message(message: Any, *, channel_url: str) -> NormalizedRecord | None:
    message_id = str(getattr(message, "id", "") or "")
    if not message_id:
        return None
    source_url = f"{channel_url.rstrip('/')}/{message_id}"
    text = str(getattr(message, "raw_text", None) or getattr(message, "text", None) or "")
    peer = getattr(message, "peer_id", None)
    channel_id = str(getattr(peer, "channel_id", "") or "")
    date = getattr(message, "date", None)
    created_at = date.isoformat() if hasattr(date, "isoformat") else (str(date) if date else "")
    media = []
    if getattr(message, "media", None) is not None:
        media.append(MediaReference(kind="telegram-media", media_index=0, metadata={"download_required": True}))
    return NormalizedRecord(
        document_id=message_id,
        platform="telegram",
        timestamp=created_at,
        source_url=source_url,
        text=text,
        media_references=media,
        collection_provenance=CollectionProvenance(
            module="telethon",
            visited_url=source_url,
            transformations=["telethon-message", "map-message"],
            metadata={"channel_id": channel_id, "media_present": bool(media)},
        ),
    )


class TelegramCollector:
    """Collect from one public/private channel using an injected Telethon client.

    Session files, phone numbers and API credentials remain deployment configuration.
    """

    def __init__(self, channel_url: str, *, limit: int = 20, client: Any) -> None:
        self.channel_url = channel_url
        self.limit = limit
        self.client = client

    def collect(self) -> CollectionResult:
        result = CollectionResult(requests_seen=1)
        rows = self.client.get_messages(self.channel_url, self.limit)
        result.bodies_seen = 1
        result.raw_items_seen = len(rows)
        for message in rows:
            record = map_message(message, channel_url=self.channel_url)
            if record:
                result.records.append(record)
        if not result.records:
            result.warnings.append(result.zero_result_warning or "No Telegram messages collected")
        return result
