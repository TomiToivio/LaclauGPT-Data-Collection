"""Small localhost capture API for the Firefox extension.

Normal CI can exercise this module without network access by calling
``capture_to_record`` directly. The HTTP server is opt-in and binds to
127.0.0.1 by default.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .capture import BrowserCapture
from .models import CollectionProvenance, MediaReference, NormalizedRecord
from .storage.local import SQLiteRecordStore


def capture_to_record(capture: BrowserCapture) -> NormalizedRecord:
    """Convert the browser capture envelope into the public interchange model."""
    document_id = capture.post_id or f"capture::{capture.capture_id}"
    media = [MediaReference(kind="unknown", url=url, media_index=index) for index, url in enumerate(capture.media_urls)]
    return NormalizedRecord(
        document_id=document_id,
        platform=capture.platform.lower(),
        author=capture.author,
        timestamp=capture.captured_at,
        source_url=capture.source_url,
        text=capture.text,
        media_references=media,
        collection_provenance=CollectionProvenance(
            captured_at=capture.captured_at,
            capture_id=capture.capture_id,
            module="browser/firefox",
            visited_url=capture.source_url,
            api_url=capture.api_url,
            transformations=["browser-capture-envelope", "capture-to-normalized-record"],
        ),
    )


class CaptureHandler(BaseHTTPRequestHandler):
    store: SQLiteRecordStore

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/capture":
            self._json(404, {"ok": False, "error": "not-found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2_000_000:
                raise ValueError("invalid payload size")
            payload = json.loads(self.rfile.read(length))
            capture = BrowserCapture.model_validate(payload)
            record = capture_to_record(capture)
            self.store.upsert(record)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"ok": False, "error": str(exc)[:200]})
            return
        self._json(200, {"ok": True, "document_id": record.document_id})

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def serve(host: str = "127.0.0.1", port: int = 8765, database: str | Path = "state/captures.sqlite3") -> None:
    """Run the opt-in local capture API."""
    CaptureHandler.store = SQLiteRecordStore(database)
    server = ThreadingHTTPServer((host, port), CaptureHandler)
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local LaclauGPT browser capture service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--database", default="state/captures.sqlite3")
    args = parser.parse_args(argv)
    serve(args.host, args.port, args.database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
