"""One-port Firefox capture backend for multiple collection configs.

This module keeps campaign/study separation in record metadata rather than in
TCP ports. It is intentionally local-only, mirroring the privacy boundary of
the existing capture server: Firefox talks to localhost, while downstream
sync may copy canonical records to shared MongoDB/S3/Redis.
"""
from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from . import __version__
from .capture_server import _decode_platform_body, git_commit
from .collectors.platforms import PARSERS, tiktok_extras
from .normalize import normalise
from .store import CollectionStore, utc_stamp
from .study import StudyConfig, load_config

COLLECTOR_VERSION = f"laclaugpt-data-collection-{__version__}"


def collection_id_for(config: StudyConfig) -> str:
    """Use the configured study id as the stable collection id."""
    value = str(config.study or "").strip()
    if not value:
        raise ValueError("study config requires a non-empty study/collection id")
    return value


def _path_segments(value: str) -> list[str]:
    try:
        return [
            part.lstrip("@").casefold()
            for part in urlparse(value).path.split("/")
            if part
        ]
    except ValueError:
        return []


def matching_targets(
    configs: list[StudyConfig], platform: str, platform_url: str
) -> list[tuple[StudyConfig, dict[str, Any] | None]]:
    """Resolve a capture to one or more configured collections.

    Explicitly configured account handles are preferred. A single-config server
    keeps legacy behaviour and accepts otherwise unattributed captures.
    """
    segments = _path_segments(platform_url)
    matches: list[tuple[StudyConfig, dict[str, Any] | None]] = []
    for config in configs:
        for account in config.accounts():
            if account.get("platform") != platform:
                continue
            handle = str(account.get("handle") or "").casefold()
            if handle and handle in segments:
                matches.append((config, account))
                break
    if matches:
        return matches
    if len(configs) == 1:
        return [(configs[0], None)]
    return []


class MultiCollectionStore(CollectionStore):
    """Collection-aware local deduplication without changing the legacy DB schema."""

    @staticmethod
    def _record_identity(record: dict) -> tuple[str, str]:
        platform, identity = CollectionStore._record_identity(record)
        collection_id = str(record.get("collection_id") or "default")
        return platform, f"{collection_id}::{identity}"


class MultiCaptureServer(ThreadingHTTPServer):
    """Shared localhost backend for several active study/collection configs."""

    def __init__(
        self,
        study_configs: list[str],
        data_root: str,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Firefox local capture server must bind to localhost")
        if not study_configs:
            raise ValueError("at least one --study-config is required")
        self.configs = [load_config(path) for path in study_configs]
        ids = [collection_id_for(config) for config in self.configs]
        if len(ids) != len(set(ids)):
            raise ValueError("study configs must use unique study/collection ids")
        self.store = MultiCollectionStore(data_root)
        self.stats = {"captures": 0, "posts": 0, "errors": 0, "skipped": 0}
        self.run_id = utc_stamp()
        self.lock = threading.RLock()
        super().__init__((host, port), Handler)

    @property
    def collection_ids(self) -> list[str]:
        return [collection_id_for(config) for config in self.configs]

    def active_configs(self) -> list[StudyConfig]:
        return [config for config in self.configs if config.in_window()]

    def tour_accounts(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for config in self.active_configs():
            collection_id = collection_id_for(config)
            for account in config.accounts():
                templates = config.platform_urls.get(str(account["platform"]), [])
                urls = [template.format(handle=account["handle"]) for template in templates] or [""]
                for url in urls:
                    rows.append({**account, "url": url, "collection_id": collection_id})
        return rows


class Handler(BaseHTTPRequestHandler):
    server: MultiCaptureServer  # type: ignore[assignment]

    def log_message(self, fmt: str, *args: Any) -> None:
        del fmt, args

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/tour":
            self._json(
                200,
                {
                    "collections": self.server.collection_ids,
                    "accounts": self.server.tour_accounts(),
                },
            )
            return
        if path == "/status":
            self._json(
                200,
                {
                    "collector": COLLECTOR_VERSION,
                    "git_commit": git_commit(),
                    "run_id": self.server.run_id,
                    "collections": self.server.collection_ids,
                    "stats": dict(self.server.stats),
                    "seen_total": self.server.store.seen_count(),
                },
            )
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if path == "/ping":
            self._json(
                200,
                {
                    "ok": True,
                    "collector": COLLECTOR_VERSION,
                    "collections": self.server.collection_ids,
                },
            )
            return
        if path != "/capture":
            self._json(404, {"error": "not found"})
            return
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "bad json"})
            return
        platform = str(data.get("platform") or "")
        if platform not in PARSERS and not platform.startswith("tiktok_"):
            self._json(400, {"error": f"unsupported platform: {platform!r}"})
            return
        try:
            count, collections = self._process_capture(data)
        except Exception as exc:  # noqa: BLE001
            with self.server.lock:
                self.server.stats["errors"] += 1
            self._json(500, {"error": str(exc)[:300]})
            return
        self._json(200, {"ok": True, "new_posts": count, "collections": collections})

    def _process_capture(self, data: dict[str, Any]) -> tuple[int, list[str]]:
        platform = str(data.get("platform") or "")
        api_url = str(data.get("api_url") or "")
        platform_url = str(data.get("platform_url") or api_url)
        captured_at = str(data.get("captured_at") or "") or datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds")
        body = data.get("body")
        if body in (None, ""):
            return 0, []
        payload = _decode_platform_body(body)
        active = self.server.active_configs()
        requested = str(data.get("collection_id") or "").strip()
        if requested:
            targets = [
                (config, self._account_for(config, platform, platform_url))
                for config in active
                if collection_id_for(config) == requested
            ]
            if not targets:
                raise ValueError(f"unknown or inactive collection_id: {requested}")
        else:
            targets = matching_targets(active, platform, platform_url)
        if not targets:
            with self.server.lock:
                self.server.stats["skipped"] += 1
            return 0, []

        collection_ids = [collection_id_for(config) for config, _ in targets]
        with self.server.lock:
            self.server.stats["captures"] += 1
            raw_ref = self.server.store.append_raw(
                platform,
                {
                    "url": api_url,
                    "ts": captured_at,
                    "platform_url": platform_url,
                    "collection_ids": collection_ids,
                    "data": payload,
                },
            )
            new_posts = 0
            for config, account in targets:
                meta = {
                    "captured_at": captured_at,
                    "collector_version": COLLECTOR_VERSION,
                    "git_commit": git_commit(),
                    "source_platform_url": platform_url,
                    "source_url": api_url,
                    "run_id": self.server.run_id,
                    "study": config.study,
                    "collection_id": collection_id_for(config),
                    "account": self._account_label(account),
                    "arena": str((account or {}).get("arena") or ""),
                }
                for record in self._records_for(platform, payload, platform_url, meta, raw_ref):
                    if self.server.store.upsert_post(record, raw_ref):
                        new_posts += 1
            self.server.stats["posts"] += new_posts
        return new_posts, collection_ids

    @staticmethod
    def _account_label(account: dict[str, Any] | None) -> str:
        if not account:
            return "unattributed"
        return f"{account.get('name', '')}:{account.get('handle', '')}"

    @staticmethod
    def _account_for(
        config: StudyConfig, platform: str, platform_url: str
    ) -> dict[str, Any] | None:
        segments = _path_segments(platform_url)
        for row in config.accounts():
            if row.get("platform") != platform:
                continue
            if str(row.get("handle") or "").casefold() in segments:
                return row
        return None

    def _records_for(
        self,
        platform: str,
        payload: Any,
        platform_url: str,
        meta: dict[str, Any],
        raw_ref: str,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if platform.startswith("tiktok_"):
            kind = platform.removeprefix("tiktok_")
            source_url = str(meta.get("source_url") or "")
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
                self._stamp_record(record, meta)
                records.append(record.model_dump(mode="json") | {
                    "collection_id": meta["collection_id"],
                    "arena": meta["arena"],
                })
            return records

        parser = PARSERS[platform]
        api_url = str(meta.get("source_url") or "")
        for item in parser.capture(payload, platform_url, api_url):
            mapped = parser.map_item(item, meta)
            record = normalise(
                platform,
                mapped,
                metadata=meta,
                raw_ref=raw_ref,
                raw_payload=item,
            )
            self._stamp_record(record, meta)
            records.append(record.model_dump(mode="json") | {
                "collection_id": meta["collection_id"],
                "arena": meta["arena"],
            })
        return records

    @staticmethod
    def _stamp_record(record: Any, meta: dict[str, Any]) -> None:
        if record.provenance:
            record.provenance[-1].metadata["collection_id"] = meta["collection_id"]
            if meta.get("arena"):
                record.provenance[-1].metadata["arena"] = meta["arena"]
        record.source.raw_metadata["collection_id"] = meta["collection_id"]
        if meta.get("arena"):
            record.source.raw_metadata["arena"] = meta["arena"]
        record.refresh_human_readable()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="laclaugpt-multi-capture")
    parser.add_argument(
        "--study-config",
        action="append",
        required=True,
        help="repeat for each active private study YAML, e.g. AI26 and Brazil26",
    )
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = MultiCaptureServer(
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
        server.store.write_manifest(
            {
                "collections": server.collection_ids,
                "collector_version": COLLECTOR_VERSION,
                "git_commit": git_commit(),
                "run_id": server.run_id,
                "stats": dict(server.stats),
                "seen_total": server.store.seen_count(),
                "run_finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
        server.store.close()
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
