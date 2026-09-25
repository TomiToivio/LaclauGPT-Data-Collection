"""End-to-end ingest/capture-server tests with synthetic payloads only."""
from __future__ import annotations

import json

from laclaugpt_data_collection.capture_server import CaptureServer, _decode_platform_body
from laclaugpt_data_collection.collectors.ingest import ingest_capture
from laclaugpt_data_collection.store import CollectionStore
from tests.fixtures import tiktok_synthetic as tfx
from tests.fixtures import x_synthetic as xfx

# Synthetic study config: no real handles anywhere.
SYNTHETIC_STUDY = {
    "study": "synthetic-validation-study",
    "window": {"start": "2020-01-01", "end": "2040-01-01"},
    "timezone": "UTC",
    "platforms": {
        "tiktok": {"enabled": True,
                   "base_urls": ["https://www.tiktok.com/@{handle}"]},
        "x": {"enabled": True,
              "base_urls": ["https://x.com/{handle}"]},
    },
    "groups": [
        {"id": "synthetic-group", "name": "Synthetic Group",
         "accounts": {"tiktok": ["synthetic_handle"], "x": ["synthetic_handle"]}},
    ],
}


def test_ingest_tiktok_item_list(tmp_path) -> None:
    records = ingest_capture(
        response=tfx.item_list_payload(),
        visited_url="https://www.tiktok.com/@synthetic_researcher",
        response_url="https://api.tiktokv.com/aweme/v1/feed/?count=10",
        metadata={"captured_at": "2026-09-15T10:00:00Z"},
        raw_ref="raw/tiktok/20260915/capture-x.ndjson",
    )
    assert len(records) == 1
    record = records[0]
    assert record.document_id == "7300000000000000001"
    assert record.platform == "tiktok"
    assert record.author == "synthetic_researcher"
    assert record.collection_provenance.visited_url.endswith("synthetic_researcher")
    assert record.raw_ref.startswith("raw/")


def test_ingest_aux_comment(tmp_path) -> None:
    records = ingest_capture(
        response={"comments": [tfx.COMMENT]},
        visited_url="https://www.tiktok.com/@synthetic_researcher",
        response_url="https://www.tiktok.com/api/comment/list/?aweme_id=7300000000000000001",
    )
    assert len(records) == 1
    record = records[0]
    assert record.platform == "tiktok_comment"
    assert record.parent_document_id == "7300000000000000001"


def test_ingest_x_timeline(tmp_path) -> None:
    records = ingest_capture(
        response=xfx.TIMELINE,
        visited_url="https://x.com/synth_user",
        response_url="https://x.com/i/api/graphql/q/UserTweets",
    )
    assert len(records) == 1
    record = records[0]
    assert record.platform == "x"
    assert record.document_id == "1500000000000000001"
    assert record.media_references  # image + video extracted


def test_ingest_unsupported_platform_returns_empty() -> None:
    assert ingest_capture(response={}, visited_url="https://example.invalid/x",
                          response_url="https://api.example.invalid/") == []


def test_decode_platform_body_prefixes() -> None:
    assert _decode_platform_body({"a": 1}) == {"a": 1}
    assert _decode_platform_body('for (;;);{"a": 1}') == {"a": 1}
    assert _decode_platform_body(")]}'\n{\"a\": 2}") == {"a": 2}


class _ServerFixture(CaptureServer):
    """CaptureServer without binding a socket (handler-level tests only)."""

    def __init__(self, data_root, tmp_path):  # noqa: super() deliberately not called
        import threading
        from types import SimpleNamespace

        self.cfg = _load_synthetic_config(tmp_path)
        self.store = CollectionStore(data_root)
        self.stats = {"captures": 0, "posts": 0, "errors": 0, "skipped": 0}
        self.run_id = "synthetic-run"
        # The handler reads the study identity from the server when building
        # capture provenance, so the socket-free fixture must expose it too.
        self.project_id = "synthetic-study"
        self.lock = threading.RLock()
        self._tz = None
        # attributes the handler touches indirectly
        self.Handler = SimpleNamespace  # never used; placeholder


def _load_synthetic_config(tmp_path):
    from laclaugpt_data_collection.study import load_config

    config_path = tmp_path / "synthetic-study.yaml"
    config_path.write_text(json.dumps(SYNTHETIC_STUDY), encoding="utf-8")
    return load_config(config_path)


def _handler(server):
    from laclaugpt_data_collection.capture_server import Handler

    handler = Handler.__new__(Handler)
    handler.server = server
    return handler


def test_capture_server_processes_tiktok(tmp_path) -> None:
    fixture = _ServerFixture(tmp_path / "data", tmp_path)
    handler = _handler(fixture)
    payload = {
        "platform": "tiktok",
        "api_url": "https://api.tiktokv.com/aweme/v1/feed/?count=10",
        "platform_url": "https://www.tiktok.com/@synthetic_researcher",
        "captured_at": "2026-09-15T10:00:00Z",
        "body": json.dumps(tfx.item_list_payload()),
    }
    assert handler._process_capture(payload) == 1
    assert handler._process_capture(payload) == 0  # dedup on second ingest
    assert fixture.store.seen_count("tiktok") == 1


def test_capture_server_routes_aux(tmp_path) -> None:
    fixture = _ServerFixture(tmp_path / "data", tmp_path)
    handler = _handler(fixture)
    payload = {
        "platform": "tiktok_comment",
        "api_url": "https://www.tiktok.com/api/comment/list/?aweme_id=7300000000000000001",
        "platform_url": "https://www.tiktok.com/@synthetic_researcher",
        "captured_at": "2026-09-15T10:00:00Z",
        "body": json.dumps({"comments": [tfx.COMMENT]}),
    }
    assert handler._process_capture(payload) == 1
    assert fixture.store.seen_count("tiktok_comment") == 1


def test_store_roundtrip_and_manifest(tmp_path) -> None:
    store = CollectionStore(tmp_path / "root")
    raw_ref = store.append_raw("tiktok", {"synthetic": True})
    assert raw_ref.startswith("raw/tiktok/")
    inserted = store.upsert_post({"platform": "tiktok", "document_id": "x-1", "text": "t"}, raw_ref)
    duplicate = store.upsert_post({"platform": "tiktok", "document_id": "x-1", "text": "t"}, raw_ref)
    assert inserted and not duplicate
    manifest = store.write_manifest({"run_id": "r", "synthetic": True})
    assert manifest.exists()
    store.checkpoint("synthetic-account", "tiktok", cursor="c1")
    assert store.get_cursor("synthetic-account", "tiktok") == "c1"
    store.close()

