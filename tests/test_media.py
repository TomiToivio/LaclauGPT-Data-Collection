"""Media handling tests (synthetic local URLs only — no network)."""
from __future__ import annotations

import base64

import pytest

from laclaugpt_data_collection.media import MediaDownloader
from laclaugpt_data_collection.store import CollectionStore

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
            del fmt, args

    server = HTTPServer(("127.0.0.1", 0), H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/media.png"
    server.shutdown()
    thread.join(timeout=5)


def _record(url: str, *, collection_id: str = "ai26") -> dict:
    return {
        "collection_id": collection_id,
        "platform": "tiktok",
        "document_id": "7301",
        "source_url": "https://www.tiktok.com/@example/video/7301",
        "media_references": [{"media_index": 0, "url": url, "kind": "image"}],
    }


def test_download_persists_checksum_and_is_idempotent(tmp_path, local_media_server) -> None:
    store = CollectionStore(tmp_path)
    downloader = MediaDownloader(store, workers=1)
    jobs = downloader.enqueue_from_records([_record(local_media_server)])
    done = downloader.run_queue(jobs)

    assert done[0]["status"] == "completed"
    assert done[0]["byte_size"] == len(TINY_PNG)
    assert done[0]["sha256"]
    assert (tmp_path / done[0]["local_path"]).exists()

    # Completed assets are not queued again on the next cron pass.
    assert downloader.enqueue_from_records([_record(local_media_server)]) == []
    store.close()


def test_failure_is_persisted_and_retryable(tmp_path) -> None:
    store = CollectionStore(tmp_path)
    downloader = MediaDownloader(store, workers=1)
    record = _record("http://127.0.0.1:9/nope.jpg")
    jobs = downloader.enqueue_from_records([record])
    done = downloader.run_queue(jobs)

    assert done[0]["status"] == "failed"
    known = store.media_known(jobs[0].media_key)
    assert known is not None
    assert known["status"] == "failed"
    # Failed assets remain eligible for a later retry.
    assert downloader.enqueue_from_records([record])
    store.close()


def test_collection_id_partitions_media_identity(tmp_path, local_media_server) -> None:
    store = CollectionStore(tmp_path)
    downloader = MediaDownloader(store, workers=1)
    ai26 = downloader.enqueue_from_records([_record(local_media_server, collection_id="ai26")])[0]
    brazil26 = downloader.enqueue_from_records(
        [_record(local_media_server, collection_id="brazil26")]
    )[0]

    assert ai26.media_key != brazil26.media_key
    assert ai26.collection_id == "ai26"
    assert brazil26.collection_id == "brazil26"
    store.close()
