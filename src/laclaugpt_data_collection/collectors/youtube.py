"""YouTube metadata collection for the Phase 1 plugin boundary."""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ..models import CollectionProvenance, MediaReference, NormalizedRecord
from .base import CollectionResult

_STATUS_RE = re.compile("[0-9][0-9][0-9]")


class YouTubeCollectionError(RuntimeError):
    """YouTube acquisition failure with orchestration-readable retry state."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        retry_after: str | None = None,
        reason: str = "",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after = retry_after
        self.reason = reason


def _raw_ref(prefix: str | None, video_id: str) -> str:
    if not prefix:
        return ""
    return f"{prefix.rstrip('/')}/{video_id}.json"


def map_video(
    info: dict[str, Any],
    *,
    raw_ref: str = "",
    transcript: str = "",
    transcript_source: str = "",
) -> NormalizedRecord | None:
    """Map source metadata to the canonical record.

    Transcript arguments remain accepted for compatibility with older callers, but
    Phase 1 collection does not request transcripts. Derived ASR/transcription belongs
    in Data Analysis.
    """
    video_id = str(info.get("id") or "")
    if not video_id:
        return None
    source_url = f"https://www.youtube.com/watch?v={video_id}"
    upload_date = str(info.get("upload_date") or "")
    created_at = upload_date
    if len(upload_date) == 8 and upload_date.isdigit():
        created_at = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    text = transcript or str(info.get("description") or info.get("title") or "")
    raw_payload = dict(info)
    if transcript:
        raw_payload["_laclaugpt_transcript"] = transcript
        raw_payload["_laclaugpt_transcript_source"] = transcript_source
    record = NormalizedRecord(
        document_id=video_id,
        platform="youtube",
        author=str(info.get("channel_id") or info.get("uploader_id") or ""),
        author_fullname=str(info.get("channel") or info.get("uploader") or ""),
        timestamp=created_at,
        source_url=source_url,
        text=text,
        raw_payload=raw_payload,
        raw_ref=raw_ref,
        raw_content_type="application/json",
        media_references=[
            MediaReference(
                kind="video",
                media_type="video",
                ref=source_url,
                url=source_url,
                metadata={
                    "video_id": video_id,
                    "download_required": True,
                    "duration": info.get("duration"),
                },
            )
        ],
        collection_provenance=CollectionProvenance(
            module="yt-dlp",
            visited_url=source_url,
            transformations=[
                "youtube-source-metadata",
                "legacy-transcript-input" if transcript else "metadata-only",
            ],
            metadata={
                "title": info.get("title"),
                "duration": info.get("duration"),
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "webpage_url": info.get("webpage_url"),
                "transcription_deferred_to_analysis": not bool(transcript),
                "transcript_source": transcript_source,
            },
        ),
    )
    record.content.title = str(info.get("title") or "") or None
    return record


def _exception_status(exc: Exception) -> tuple[int | None, str | None]:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    headers = getattr(response, "headers", {}) or {}
    retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    if isinstance(status, int):
        return status, str(retry_after) if retry_after not in (None, "") else None
    match = _STATUS_RE.search(str(exc))
    return (int(match.group(0)), None) if match else (None, None)


def _collection_error(exc: Exception) -> YouTubeCollectionError:
    status, retry_after = _exception_status(exc)
    message = str(exc)
    lowered = message.lower()
    quota = "quota" in lowered and ("exceed" in lowered or "limit" in lowered)
    rate_limited = status == 429 or "too many requests" in lowered
    server_error = status is not None and 500 <= status < 600
    transport_error = isinstance(exc, (TimeoutError, ConnectionError, OSError))
    retryable = bool(rate_limited or server_error or transport_error)
    reason = (
        "quota_exceeded"
        if quota
        else "rate_limited"
        if rate_limited
        else "server_error"
        if server_error
        else "transport_error"
        if transport_error
        else "terminal_source_error"
    )
    if quota:
        retryable = False
    return YouTubeCollectionError(
        message or exc.__class__.__name__,
        retryable=retryable,
        status_code=status,
        retry_after=retry_after,
        reason=reason,
    )


class YouTubeCollector:
    """Collect bounded YouTube metadata pages without doing downstream analysis."""

    def __init__(
        self,
        video_urls: list[str],
        *,
        page_size: int = 25,
        cursor: str | None = None,
        raw_ref_prefix: str | None = None,
        info_loader: Callable[[str], dict[str, Any]] | None = None,
        transcript: bool = False,
        whisper_fallback: Any | None = None,
    ) -> None:
        if page_size < 1:
            raise ValueError("youtube page_size must be at least 1")
        self.video_urls = video_urls
        self.page_size = page_size
        self.cursor = cursor
        self.raw_ref_prefix = raw_ref_prefix
        self.info_loader = info_loader
        self.transcript = transcript
        self.whisper_fallback = whisper_fallback

    def _video_info(self, url: str) -> dict[str, Any]:
        if self.info_loader is not None:
            return dict(self.info_loader(url) or {})
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("Install the 'youtube' extra for yt-dlp support") from exc
        try:
            with yt_dlp.YoutubeDL(
                {"quiet": True, "no_warnings": True, "skip_download": True}
            ) as ydl:
                return dict(ydl.extract_info(url, download=False) or {})
        except Exception as exc:
            raise _collection_error(exc) from exc

    def _offset(self) -> int:
        if self.cursor in (None, ""):
            return 0
        try:
            offset = int(str(self.cursor))
        except ValueError as exc:
            raise ValueError("youtube cursor must be a non-negative integer offset") from exc
        if offset < 0:
            raise ValueError("youtube cursor must be a non-negative integer offset")
        return offset

    def collect(self) -> CollectionResult:
        result = CollectionResult()
        start = self._offset()
        end = min(start + self.page_size, len(self.video_urls))
        for url in self.video_urls[start:end]:
            result.requests_seen += 1
            try:
                info = self._video_info(url)
            except YouTubeCollectionError:
                raise
            except Exception as exc:
                raise _collection_error(exc) from exc
            result.bodies_seen += 1
            if not info:
                continue
            result.raw_items_seen += 1
            video_id = str(info.get("id") or "")
            record = map_video(
                info,
                raw_ref=_raw_ref(self.raw_ref_prefix, video_id) if video_id else "",
            )
            if record:
                result.records.append(record)
        if end < len(self.video_urls):
            result.next_cursor = str(end)
        if not result.records:
            result.warnings.append(result.zero_result_warning or "No YouTube videos collected")
        return result
