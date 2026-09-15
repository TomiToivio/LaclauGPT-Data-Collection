"""Optional media downloading — queued, checksummed, deduplicated.

Adapted from the public `collector/backend/media.py` in
TomiToivio/LaclauGPT-Discourse-Analysis. Media downloading is asynchronous
relative to browser capture: capture never waits for large files. Each
MediaReference carries status/failure metadata so the record stays usable
even when a signed CDN URL has expired (TikTok/Instagram common case).

Storage behind an interface: filesystem today, Allas/S3 via the storage
adapters later. Downloaded research media are NEVER committed to Git.
"""
from __future__ import annotations

import hashlib
import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "Mozilla/5.0 (LaclauGPT collector; research)"}


def media_filename(platform: str, post_id: str, media_index: int,
                   ext: str = "") -> str:
    """Deterministic collision-resistant name (never use captions)."""
    return f"{platform}_{post_id}_{media_index:03d}{ext}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ext_for(url: str, media_kind: str) -> str:
    tail = url.split("?")[0].rsplit(".", 1)
    if len(tail) == 2 and tail[1].lower() in {"jpg", "jpeg", "png", "webp",
                                              "mp4", "webm", "gif"}:
        return "." + tail[1].lower()
    return {"video": ".mp4", "image": ".jpg", "thumbnail": ".jpg"}.get(
        media_kind, ".bin")


class MediaStore:
    """Local filesystem media storage (swap for object storage later)."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, platform: str, post_id: str, media_index: int,
                 ext: str) -> Path:
        directory = self.root / platform
        directory.mkdir(parents=True, exist_ok=True)
        return directory / media_filename(platform, post_id, media_index, ext)

    def exists_verified(self, path: Path, sha: str | None) -> bool:
        if not path.exists():
            return False
        return sha is None or sha256_file(path) == sha


class MediaQueue:
    """Serial queue worker; capture loops enqueue and move on."""

    def __init__(self, store: MediaStore):
        self.store = store

    def download(self, ref: dict[str, Any]) -> dict[str, Any]:
        """Download one media-reference dict; dedupe by path; never raise.

        Input keys: platform, post_id, media_index, url, kind.
        Output keys add: status, local_path, byte_size, sha256, mime_type,
        http_status, failure_reason, downloaded_at.
        """
        if ref.get("status") == "downloaded":
            return ref
        url = str(ref.get("url") or "")
        if not url.startswith("http"):
            ref["status"] = "failed"
            ref["failure_reason"] = "missing or non-http url"
            return ref
        dest = self.store.path_for(
            ref["platform"], str(ref["post_id"]), int(ref.get("media_index") or 0),
            _ext_for(url, str(ref.get("kind") or "")),
        )
        # dedupe: retry must not create a second copy
        if dest.exists():
            self._mark_downloaded(ref, dest)
            return ref
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
                ref["http_status"] = resp.status
                ref["mime_type"] = resp.headers.get("Content-Type")
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(data)
            tmp.rename(dest)
            self._mark_downloaded(ref, dest)
        except Exception as exc:  # noqa: BLE001 — failures recorded, never fatal
            ref["status"] = "failed"
            ref["failure_reason"] = str(exc)[:200]
        return ref

    @staticmethod
    def _mark_downloaded(ref: dict[str, Any], dest: Path) -> None:
        ref["local_path"] = str(dest)
        ref["byte_size"] = dest.stat().st_size
        ref["sha256"] = sha256_file(dest)
        ref["status"] = "downloaded"
        ref["downloaded_at"] = datetime.now(timezone.utc).isoformat()


def process_queue(refs: list[dict[str, Any]], store: MediaStore) -> list[dict[str, Any]]:
    """Drain the queue (serial today; threads later if needed)."""
    queue = MediaQueue(store)
    return [queue.download(ref) for ref in refs]


def media_manifest(refs: list[dict[str, Any]], manifest_dir: Path) -> Path:
    """Write one media-run manifest; returns the manifest path."""
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / f"media_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.json"
    payload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "downloads": [
            {k: ref.get(k) for k in (
                "platform", "post_id", "status", "sha256", "local_path",
                "failure_reason")} for ref in refs],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path