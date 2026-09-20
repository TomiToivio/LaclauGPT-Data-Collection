"""Telegram/Telethon adapter with runtime-only credentials and sessions."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit

from ..models import CollectionProvenance, MediaReference, NormalizedRecord
from .base import CollectionResult


class TelegramCollectionError(RuntimeError):
    """Telegram acquisition failure with orchestration-readable retry state."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        retry_after: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


def _channel_identity(channel: str, channel_id: str = "") -> str:
    value = channel.strip()
    parts = urlsplit(value)
    if parts.scheme in {"http", "https"} and parts.netloc:
        path = parts.path.strip("/")
        if path:
            return path.split("/", 1)[0].lower()
    if value.startswith("@"):
        return value[1:].lower()
    if value:
        return value.lower()
    return channel_id or "unknown"


def _message_source_url(channel: str, message_id: str, channel_id: str = "") -> str:
    value = channel.strip()
    parts = urlsplit(value)
    if parts.scheme in {"http", "https"} and parts.netloc:
        return f"{value.rstrip('/')}/{message_id}"
    return f"telegram:{_channel_identity(value, channel_id)}:{message_id}"


def _message_payload(message: Any) -> Any:
    to_dict = getattr(message, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(message, Mapping):
        return dict(message)
    date = getattr(message, "date", None)
    return {
        "id": getattr(message, "id", None),
        "raw_text": getattr(message, "raw_text", None),
        "text": getattr(message, "text", None),
        "date": date.isoformat() if hasattr(date, "isoformat") else date,
        "peer_id": str(getattr(message, "peer_id", "") or ""),
        "media_present": getattr(message, "media", None) is not None,
    }


def map_message(
    message: Any,
    *,
    channel: str | None = None,
    channel_url: str | None = None,
    raw_ref: str | None = None,
) -> NormalizedRecord | None:
    """Map one Telethon message to the canonical Collection record.

    channel_url is retained as a Phase 0/legacy compatibility alias.
    """
    channel = str(channel or channel_url or "")
    if not channel:
        raise ValueError("Telegram channel identity is required")

    message_id = str(getattr(message, "id", "") or "")
    if not message_id:
        return None
    peer = getattr(message, "peer_id", None)
    channel_id = str(getattr(peer, "channel_id", "") or "")
    source_url = _message_source_url(channel, message_id, channel_id)
    text = str(getattr(message, "raw_text", None) or getattr(message, "text", None) or "")
    date = getattr(message, "date", None)
    created_at = date.isoformat() if hasattr(date, "isoformat") else (str(date) if date else "")
    media = []
    if getattr(message, "media", None) is not None:
        media.append(
            MediaReference(
                kind="telegram-media",
                media_index=0,
                metadata={
                    "download_required": True,
                    "telegram_message_id": message_id,
                    "telegram_channel_id": channel_id,
                },
            )
        )
    record = NormalizedRecord(
        document_id=message_id,
        platform="telegram",
        timestamp=created_at,
        source_url=source_url,
        text=text,
        media_references=media,
        raw_ref=raw_ref or "",
        raw_payload=_message_payload(message),
        raw_content_type="application/json",
        collection_provenance=CollectionProvenance(
            module="telethon",
            visited_url=source_url,
            transformations=["telethon-message", "map-message"],
            metadata={
                "channel": channel,
                "channel_id": channel_id,
                "media_present": bool(media),
            },
        ),
    )
    record.source_native_ids["telegram_message_id"] = message_id
    if channel_id:
        record.source_native_ids["telegram_channel_id"] = channel_id
    record.source.raw_metadata.update(
        {
            "telegram_channel": channel,
            "telegram_channel_identity": _channel_identity(channel, channel_id),
        }
    )
    return record


class TelegramCollector:
    """Collect one Telegram channel using Telethon.

    Real target names, API credentials and session material are runtime-private. Tests
    inject a synthetic client and never authenticate against Telegram.
    """

    def __init__(
        self,
        channel: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
        client: Any | None = None,
        api_id: int | None = None,
        api_hash: str | None = None,
        session: str | None = None,
        raw_ref_prefix: str | None = None,
    ) -> None:
        self.channel = channel
        self.limit = limit
        self.cursor = cursor
        self.client = client
        self.api_id = api_id
        self.api_hash = api_hash
        self.session = session
        self.raw_ref_prefix = raw_ref_prefix.rstrip("/") if raw_ref_prefix else None

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        if self.api_id is None or not self.api_hash or not self.session:
            raise ValueError(
                "Telegram requires runtime api_id, api_hash and a pre-authenticated session"
            )
        try:
            from telethon.sync import TelegramClient
        except ImportError as exc:
            raise RuntimeError("Install the 'telegram' extra to collect from Telegram") from exc
        client = TelegramClient(self.session, self.api_id, self.api_hash)
        client.connect()
        if hasattr(client, "is_user_authorized") and not client.is_user_authorized():
            client.disconnect()
            raise RuntimeError("Telegram session is not authenticated; authorize it outside CI")
        return client

    @staticmethod
    def _failure_state(exc: Exception) -> tuple[bool, str | None]:
        seconds = getattr(exc, "seconds", None)
        retry_after = str(seconds) if seconds not in (None, "") else None
        name = type(exc).__name__.lower()
        retryable = (
            retry_after is not None
            or "floodwait" in name
            or "servererror" in name
            or "timedout" in name
            or isinstance(exc, (ConnectionError, TimeoutError, OSError, URLError))
        )
        return retryable, retry_after

    def _raw_ref(self, message_id: str, channel_id: str = "") -> str | None:
        if not self.raw_ref_prefix:
            return None
        identity = _channel_identity(self.channel, channel_id).replace("/", "_")
        return f"{self.raw_ref_prefix}/{identity}/{message_id}.json"

    def collect(self) -> CollectionResult:
        result = CollectionResult(requests_seen=1)
        client = self._client()
        kwargs: dict[str, Any] = {"limit": self.limit}
        if self.cursor:
            try:
                kwargs["max_id"] = int(self.cursor)
            except ValueError as exc:
                raise ValueError("Telegram cursor must be a numeric message ID") from exc
        try:
            rows = list(client.get_messages(self.channel, **kwargs))
        except Exception as exc:  # Telethon exposes several RPC/transport exception classes
            retryable, retry_after = self._failure_state(exc)
            raise TelegramCollectionError(
                str(exc),
                retryable=retryable,
                retry_after=retry_after,
            ) from exc
        result.bodies_seen = 1
        result.raw_items_seen = len(rows)
        for message in rows:
            peer = getattr(message, "peer_id", None)
            channel_id = str(getattr(peer, "channel_id", "") or "")
            message_id = str(getattr(message, "id", "") or "")
            record = map_message(
                message,
                channel=self.channel,
                raw_ref=self._raw_ref(message_id, channel_id) if message_id else None,
            )
            if record:
                result.records.append(record)
        if rows:
            last_id = getattr(rows[-1], "id", None)
            result.next_cursor = str(last_id) if last_id not in (None, "") else None
        if not result.records:
            result.warnings.append(result.zero_result_warning or "No Telegram messages collected")
        return result
