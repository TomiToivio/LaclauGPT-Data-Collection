"""Local HTTP capture backend for the LaclauGPT Firefox extension.

The extension captures public platform API response bodies and POSTs them to
this localhost service. The backend validates the study window, parses
platform payloads, normalizes records and persists raw plus canonical output.

Normal CI can also exercise ``capture_to_record`` directly without sockets.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import struct
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import __version__
from .capture import BrowserCapture
from .collectors.platforms import PARSERS, tiktok_extras
from .media import CaptureTimeMediaHandoff
from .models import CanonicalRecord, CollectionProvenance, MediaReference, NormalizedRecord
from .normalize import normalise
from .store import CollectionStore, utc_stamp
from .study import StudyConfig, load_config
from .web_fetch import external_urls_for_record, fetch_web_child

COLLECTOR_VERSION = f"laclaugpt-data-collection-{__version__}"
_git_commit_cache: str | None = None


def capture_to_record(capture: BrowserCapture) -> NormalizedRecord:
    """Convert a simple page-capture envelope into the canonical record adapter."""
    document_id = capture.post_id or f"capture::{capture.capture_id}"
    media = [
        MediaReference(kind="unknown", url=url, media_index=index)
        for index, url in enumerate(capture.media_urls)
    ]
    return NormalizedRecord(
        document_id=document_id,
        platform=capture.platform.lower(),
        author=capture.author,
        timestamp=capture.captured_at,
        source_url=capture.source_url,
        text=capture.text,
        media_references=media,
        raw_payload=capture.model_dump(mode="json"),
        raw_content_type="application/json",
        collection_provenance=CollectionProvenance(
            captured_at=capture.captured_at,
            capture_id=capture.capture_id,
            module="browser/firefox",
            visited_url=capture.source_url,
            api_url=capture.api_url,
            transformations=["browser-capture-envelope", "capture-to-canonical-record"],
        ),
    )


def git_commit(repo: Path | None = None) -> str:
    """Best-effort collector build provenance (empty outside a git checkout)."""
    global _git_commit_cache
    if _git_commit_cache is None:
        cwd = repo or Path.cwd()
        try:
            _git_commit_cache = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            ).stdout.strip()
        except Exception:  # noqa: BLE001
            _git_commit_cache = ""
    return _git_commit_cache


def _complete_media_response(status_code: int, content_range: str, byte_size: int) -> bool:
    """Accept only complete successful responses, never unassembled range fragments."""
    if status_code == 200:
        return byte_size > 0
    if status_code != 206:
        return False
    match = re.fullmatch(r"bytes 0-(\d+)/(\d+)", content_range)
    return (
        match is not None
        and int(match.group(1)) + 1 == int(match.group(2))
        and byte_size == int(match.group(2))
    )


def _decode_platform_body(body: Any) -> Any:
    """Accept JSON objects/strings or common JSON response prefixes."""
    if isinstance(body, (dict, list)):
        return body
    if not isinstance(body, str):
        raise ValueError("capture body is not text or JSON")
    text = body.lstrip("\ufeff \t\r\n")
    if text.startswith("for (;;);"):
        text = text[len("for (;;);"):].lstrip()
    if text.startswith(")]}'"):
        text = text.split("\n", 1)[1] if "\n" in text else text[4:].lstrip(", \t\r\n")
    return json.loads(text)


class CaptureServer(ThreadingHTTPServer):
    """HTTP endpoints: /capture, /ping, /tour and /status."""

    def __init__(
        self,
        study_config: str,
        data_root: str,
        host: str = "127.0.0.1",
        port: int = 8765,
        project_id: str = "",
        capture_media_inline: bool = False,
        capture_media_max_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Firefox local capture server must bind to localhost")
        self.cfg: StudyConfig = load_config(study_config)
        self.store = CollectionStore(data_root)
        self.media_handoff = CaptureTimeMediaHandoff(self.store)
        self.capture_media_inline = capture_media_inline
        self.capture_media_max_bytes = max(1, capture_media_max_bytes)
        self.stats = {
            "captures": 0,
            "posts": 0,
            "errors": 0,
            "skipped": 0,
            "web_children": 0,
            "web_fetch_errors": 0,
            "media_captures": 0,
            "media_linked": 0,
            "media_rejected": 0,
        }
        self.run_id = utc_stamp()
        self.project_id = project_id.strip()
        self.lock = threading.RLock()
        self._tz = self._load_timezone(self.cfg.timezone)
        super().__init__((host, port), Handler)

    @staticmethod
    def _load_timezone(name: str):
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            return timezone.utc

    def local_today(self):
        return datetime.now(self._tz).date()

    def active(self) -> bool:
        return self.cfg.in_window(self.local_today())

    def tour_accounts(self) -> list[dict]:
        """Return one navigation row per configured account page URL."""
        if not self.active():
            return []
        rows: list[dict] = []
        for account in self.cfg.accounts():
            templates = self.cfg.platform_urls.get(account["platform"], [])
            urls = [tpl.format(handle=account["handle"]) for tpl in templates] or [""]
            for url in urls:
                rows.append({**account, "url": url})
        return rows


class Handler(BaseHTTPRequestHandler):
    server: CaptureServer  # type: ignore[assignment]

    def log_message(self, fmt, *args):
        del fmt, args

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        if path == "/media-capture":
            self._capture_media(length)
            return
        raw = self.rfile.read(length) if length else b"{}"

        if path == "/ping":
            self._json(200, {
                "ok": True,
                "collector": COLLECTOR_VERSION,
                "active": self.server.active(),
            })
            return
        if path != "/capture":
            self._json(404, {"error": "not found"})
            return
        if not self.server.active():
            with self.server.lock:
                self.server.stats["skipped"] += 1
            self._json(200, {
                "ok": True,
                "skipped": "outside study window",
                "date": str(self.server.local_today()),
            })
            return

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "bad json"})
            return

        platform = data.get("platform", "")
        if platform not in PARSERS and not platform.startswith("tiktok_"):
            self._json(400, {"error": f"unsupported platform: {platform!r}"})
            return

        with self.server.lock:
            self.server.stats["captures"] += 1
        try:
            new_posts = self._process_capture(data)
            self._json(200, {
                "ok": True,
                "new_posts": new_posts,
                "posts_total": self.server.stats["posts"],
            })
        except Exception as exc:  # noqa: BLE001
            with self.server.lock:
                self.server.stats["errors"] += 1
            self._json(500, {"error": str(exc)[:300]})

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/tour":
            cfg = self.server.cfg
            self._json(200, {
                "active": self.server.active(),
                "date": str(self.server.local_today()),
                "study": cfg.study,
                "accounts": self.server.tour_accounts(),
                "window": {"start": str(cfg.start), "end": str(cfg.end)},
                "timezone": cfg.timezone,
            })
        elif path == "/status":
            self._json(200, {
                "collector": COLLECTOR_VERSION,
                "git_commit": git_commit(),
                "run_id": self.server.run_id,
                "study": self.server.cfg.study,
                "active": self.server.active(),
                "date": str(self.server.local_today()),
                "stats": dict(self.server.stats),
                "seen_total": self.server.store.seen_count(),
                "capture_media_inline": self.server.capture_media_inline,
                "capture_media_max_bytes": self.server.capture_media_max_bytes,
            })
        else:
            self._json(404, {"error": "not found"})

    def _capture_media(self, length: int) -> None:
        """Accept length-prefixed metadata plus browser-authorized media bytes."""
        if not self.server.capture_media_inline:
            self.close_connection = True
            self._json(404, {"error": "media capture disabled"})
            return
        maximum = self.server.capture_media_max_bytes + 65_540
        if length < 5 or length > maximum:
            self.close_connection = True
            with self.server.lock:
                self.server.stats["media_rejected"] += 1
            self._json(413, {"error": "media capture exceeds configured bound"})
            return
        raw = self.rfile.read(length)
        metadata_length = struct.unpack(">I", raw[:4])[0]
        if metadata_length < 2 or metadata_length > 65_536 or 4 + metadata_length >= len(raw):
            self._json(400, {"error": "bad media envelope"})
            return
        try:
            metadata = json.loads(raw[4:4 + metadata_length])
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "bad media metadata"})
            return
        body = raw[4 + metadata_length:]
        status_code = int(metadata.get("status_code") or 0)
        content_range = str(metadata.get("content_range") or "")
        if not _complete_media_response(status_code, content_range, len(body)):
            self._json(422, {"error": "partial or unsuccessful media response"})
            return
        url = str(metadata.get("url") or "")
        mime_type = str(metadata.get("mime_type") or "")
        host = (urlparse(url).hostname or "").casefold()
        tiktok_host = host == "tiktok.com" or host.endswith(".tiktok.com")
        if not tiktok_host or not mime_type.casefold().startswith("video/"):
            self._json(400, {"error": "unsupported media origin or type"})
            return
        with self.server.lock:
            result = self.server.media_handoff.capture(url, body, mime_type)
            self.server.stats["media_captures"] += 1
            self.server.stats["media_linked"] += int(result["linked"])
        self._json(200, {"ok": True, **result})
    def _process_capture(self, data: dict[str, Any]) -> int:
        platform = data.get("platform", "")
        api_url = data.get("api_url", "")
        platform_url = data.get("platform_url", "") or api_url
        captured_at = data.get("captured_at", "") or datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds")
        body = data.get("body")
        if body in (None, ""):
            return 0

        payload = _decode_platform_body(body)
        account = self._account_for(platform, platform_url)
        meta = {
            "captured_at": captured_at,
            "collector_version": COLLECTOR_VERSION,
            "git_commit": git_commit(),
            "source_platform_url": platform_url,
            "source_url": api_url,
            "run_id": self.server.run_id,
            "study": self.server.cfg.study,
            "project_id": self.server.project_id,
            "collection_id": self.server.project_id,
            "account": account,
        }

        with self.server.lock:
            raw_ref = self.server.store.append_raw(platform, {
                "url": api_url,
                "ts": captured_at,
                "platform_url": platform_url,
                "data": payload,
            })
            new_posts = 0
            new_records: list[dict] = []
            records = self._records_for(platform, payload, api_url, platform_url, meta, raw_ref)
            for record in records:
                inserted = self.server.store.upsert_post(record, raw_ref)
                if getattr(self.server, "capture_media_inline", False):
                    self.server.stats["media_linked"] += (
                        self.server.media_handoff.register_record(record)
                    )
                if inserted:
                    new_posts += 1
                    new_records.append(record)
            self.server.stats["posts"] += new_posts

        if (
            platform == "x"
            and new_records
            and self.server.cfg.fetch_external_links_as_web_sources
        ):
            self._fetch_web_children(new_records)
        return new_posts

    def _fetch_web_children(self, parent_records: list[dict]) -> None:
        """Fetch external X links after parent durability; failures stay non-fatal."""
        for payload in parent_records:
            try:
                parent = CanonicalRecord.model_validate(payload)
            except Exception:  # noqa: BLE001
                continue
            arena = str(parent.source.raw_metadata.get("arena") or "")
            for url in external_urls_for_record(parent):
                outcome = fetch_web_child(
                    url,
                    parent,
                    collection_id=self.server.cfg.study,
                    arena=arena,
                )
                if outcome.record is None:
                    with self.server.lock:
                        self.server.stats["web_fetch_errors"] += 1
                    if self.server.cfg.link_fetch_failure_blocks_parent:
                        raise RuntimeError(f"WEB child fetch failed for {url}: {outcome.error}")
                    continue
                child = outcome.record.model_dump(mode="json")
                with self.server.lock:
                    if self.server.store.upsert_post(child, ""):
                        self.server.stats["web_children"] += 1

    def _records_for(
        self,
        platform: str,
        payload: Any,
        api_url: str,
        platform_url: str,
        meta: dict[str, Any],
        raw_ref: str,
    ) -> list[dict]:
        records: list[dict] = []
        if platform.startswith("tiktok_"):
            kind = platform.removeprefix("tiktok_")
            source_url = api_url if kind in api_url else f"api/{kind}/list/"
            for raw_item in tiktok_extras.capture(payload, platform_url, source_url):
                mapped = tiktok_extras.map_item(raw_item, meta)
                mapped["record_kind"] = kind
                record = tiktok_extras.to_record(mapped)
                if record is None:
                    continue
                record.source.raw_ref = raw_ref
                record.raw_capture.ref = raw_ref
                record.raw_capture.payload = raw_item
                record.raw_capture.content_type = "application/json"
                record.raw_capture.captured_at = str(meta.get("captured_at") or "") or None
                record.raw_capture.metadata["preservation"] = "exact-item-plus-full-response-ref"
                record.refresh_human_readable()
                records.append(record.model_dump(mode="json"))
            return records

        parser = PARSERS[platform]
        for item in parser.capture(payload, platform_url, api_url):
            mapped = parser.map_item(item, meta)
            record = normalise(
                platform,
                mapped,
                metadata=meta,
                raw_ref=raw_ref,
                raw_payload=item,
            )
            records.append(record.model_dump(mode="json"))
        return records

    def _account_for(self, platform: str, platform_url: str) -> str:
        try:
            segments = [
                segment.lstrip("@").casefold()
                for segment in urlparse(platform_url).path.split("/")
                if segment
            ]
        except ValueError:
            segments = []
        for row in self.server.cfg.accounts():
            if row["platform"] != platform:
                continue
            if str(row["handle"]).casefold() in segments:
                return f"{row['name']}:{row['handle']}"
        return "unattributed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="laclaugpt-capture-server")
    parser.add_argument("--study-config", required=True,
                        help="study YAML configuration (ignored local file)")
    parser.add_argument("--data-root", required=True,
                        help="persistent collection data root")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--capture-media-inline", action="store_true")
    parser.add_argument("--capture-media-max-bytes", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args(argv)
    server = CaptureServer(
        args.study_config,
        args.data_root,
        host=args.host,
        port=args.port,
        capture_media_inline=args.capture_media_inline,
        capture_media_max_bytes=args.capture_media_max_bytes,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.store.write_manifest({
            "study": server.cfg.study,
            "collector_version": COLLECTOR_VERSION,
            "git_commit": git_commit(),
            "run_id": server.run_id,
            "stats": dict(server.stats),
            "seen_total": server.store.seen_count(),
            "missing_candidates": server.cfg.missing_candidates(),
            "window": {"start": str(server.cfg.start), "end": str(server.cfg.end)},
            "timezone": server.cfg.timezone,
            "run_finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        server.store.close()
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
