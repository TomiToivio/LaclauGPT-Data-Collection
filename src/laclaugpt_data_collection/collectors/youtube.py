"""YouTube metadata/transcript collection with lazy optional dependencies."""
from __future__ import annotations

from typing import Any

from ..models import CollectionProvenance, NormalizedRecord
from .base import CollectionResult


def map_video(info: dict[str, Any], *, transcript: str = "", transcript_source: str = "") -> NormalizedRecord | None:
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
    return NormalizedRecord(
        document_id=video_id,
        platform="youtube",
        author=str(info.get("channel_id") or info.get("uploader_id") or ""),
        author_fullname=str(info.get("channel") or info.get("uploader") or ""),
        timestamp=created_at,
        source_url=source_url,
        text=text,
        raw_payload=raw_payload,
        raw_content_type="application/json",
        collection_provenance=CollectionProvenance(
            module="yt-dlp",
            visited_url=source_url,
            transformations=["youtube-metadata", "transcript" if transcript else "description-fallback"],
            metadata={
                "title": info.get("title"),
                "duration": info.get("duration"),
                "transcript_source": transcript_source,
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
            },
        ),
    )


class YouTubeCollector:
    def __init__(self, video_urls: list[str], *, transcript: bool = True, whisper_fallback: Any | None = None) -> None:
        self.video_urls = video_urls
        self.transcript = transcript
        self.whisper_fallback = whisper_fallback

    def _video_info(self, url: str) -> dict[str, Any]:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("Install the 'youtube' extra for yt-dlp support") from exc
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            return dict(ydl.extract_info(url, download=False) or {})

    def _transcript(self, video_id: str) -> tuple[str, str]:
        if not self.transcript:
            return "", ""
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            rows = YouTubeTranscriptApi.get_transcript(video_id)
            return " ".join(str(row.get("text") or "") for row in rows), "youtube-transcript-api"
        except Exception:
            if self.whisper_fallback is not None:
                text = self.whisper_fallback(video_id)
                return (str(text or ""), "whisper-fallback" if text else "")
            return "", ""

    def collect(self) -> CollectionResult:
        result = CollectionResult()
        for url in self.video_urls:
            result.requests_seen += 1
            info = self._video_info(url)
            result.bodies_seen += 1
            if not info:
                continue
            result.raw_items_seen += 1
            transcript, source = self._transcript(str(info.get("id") or ""))
            record = map_video(info, transcript=transcript, transcript_source=source)
            if record:
                result.records.append(record)
        if not result.records:
            result.warnings.append(result.zero_result_warning or "No YouTube videos collected")
        return result
