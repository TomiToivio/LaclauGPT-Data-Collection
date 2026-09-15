"""Media handling tests (synthetic local URLs only — no network)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from laclaugpt_data_collection.media import (
    MediaQueue,
    MediaStore,
    media_filename,
    media_manifest,
    process_queue,
    sha256_file,
)

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture()
def local_media_server():
    """Serve one synthetic PNG on an ephemeral local port; no platform contact."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(TINY_PNG)))
            self.end_headers()
            self.wfile.write(TINY_PNG)

        def log_message(self, fmt, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/media.png"
    server.shutdown()
    thread.join(timeout=5)


def test_media_filename_is_deterministic() -> None:
    assert media_filename("tiktok", "7301", 0, ".mp4") == "tiktok_7301_000.mp4"


def test_download_and_checksum(tmp_path, local_media_server) -> None:
    store = MediaStore(tmp_path / "media")
    ref = {"platform": "tiktok", "post_id": "7301", "media_index": 0,
           "url": local_media_server, "kind": "image"}
    done = process_queue([ref], store)
    assert done[0]["status"] == "downloaded"
    path = Path(done[0]["local_path"])
    assert path.exists()
    assert done[0]["sha256"] == sha256_file(path)
    assert done[0]["byte_size"] == len(TINY_PNG)
    # re-download: dedupe by existing file
    again = process_queue([{"platform": "tiktok", "post_id": "7301",
                            "media_index": 0, "url": local_media_server,
                            "kind": "image"}], store)
    assert again[0]["status"] == "downloaded"
    assert again[0]["local_path"] == done[0]["local_path"]


def test_failure_is_recorded_never_raised(tmp_path) -> None:
    store = MediaStore(tmp_path / "media")
    ref = {"platform": "x", "post_id": "p1", "media_index": 1,
           "url": "http://127.0.0.1:9/nope.jpg", "kind": "image"}
    done = MediaQueue(store).download(ref)
    assert done["status"] == "failed"
    assert done["failure_reason"]


def test_manifest_written(tmp_path, local_media_server) -> None:
    store = MediaStore(tmp_path / "media")
    refs = [{"platform": "tiktok", "post_id": "7301", "media_index": 0,
             "url": local_media_server, "kind": "image"}]
    done = process_queue(refs, store)
    manifest = media_manifest(done, tmp_path / "manifests")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["downloads"][0]["status"] == "downloaded"