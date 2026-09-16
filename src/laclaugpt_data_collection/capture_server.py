"""Local HTTP capture backend for the LaclauGPT Firefox extension.

The extension captures public platform API response bodies and POSTs them to
this localhost service. The backend validates the study window, parses
platform payloads, normalizes records and persists raw plus canonical output.

Normal CI can also exercise ``capture_to_record`` directly without sockets.
"""
from __future__ import annotations

import argparse
import json
import subprocess
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
    ) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Firefox local capture server must bind to localhost")
        self.cfg: StudyConfig = load_config(study_config)
        self.store = CollectionStore(data_root)
        self.stats = {
            "captures": 0,
            "posts": 0,
            "errors": 0,
            "skipped": 0,
            "web_children": 0,
            "web_fetch_errors": 0,
        }
        self.run_id = utc_stamp()
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
            })
        else:
            self._json(404, {"error": "not found"})

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
                if self.server.store.upsert_post(record, raw_ref):
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
    args = parser.parse_args(argv)
    server = CaptureServer(
        args.study_config,
        args.data_root,
        host=args.host,
        port=args.port,
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
