"""Phase 1 Instagram browser vertical-slice contract for issue #132.

Public CI is synthetic/offline. Real Firefox/Instagram activation remains gated on
issue #105's documented researcher-triggered Firefox/TikTok smoke.
"""
from __future__ import annotations

import json

import pytest

from laclaugpt_data_collection.capture_server import (
    CaptureServer,
    Handler,
    _decode_platform_body,
)
from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.models import CanonicalRecord
from laclaugpt_data_collection.store import CollectionStore
from tests.fixtures import instagram_synthetic as fx


def _canonical_record() -> CanonicalRecord:
    handler = Handler.__new__(Handler)
    api_url = "https://www.instagram.com/api/v1/feed/timeline/"
    platform_url = "https://www.instagram.com/reel/SynthReel132/"
    meta = {
        "captured_at": "2026-09-20T12:00:00Z",
        "capture_id": "synthetic-browser-capture-132",
        "collector_version": "test",
        "git_commit": "test",
        "source_platform_url": platform_url,
        "source_url": api_url,
        "run_id": "issue-132-test",
        "study": "synthetic",
        "account": "synthetic",
    }
    rows = handler._records_for(
        "instagram",
        fx.PHASE1_REEL_RESPONSE,
        api_url,
        platform_url,
        meta,
        "raw/instagram/synthetic-132.ndjson",
    )
    assert len(rows) == 1
    return CanonicalRecord.model_validate(rows[0])


def test_instagram_browser_capture_reaches_canonical_record_with_native_reference() -> None:
    record = _canonical_record()

    assert record.source.platform == "instagram"
    assert record.source_url == "https://www.instagram.com/reel/SynthReel132"
    assert record.source_native_ids["document_id"] == "SynthReel132"
    assert record.source_native_ids["parent_document_id"] == "3300000000000000131"
    assert record.source.raw_metadata["parent_document_id"] == "3300000000000000131"
    assert record.source.raw_metadata["native_relationship_type"] == "reference"
    assert record.raw_capture.ref == "raw/instagram/synthetic-132.ndjson"
    assert record.raw_capture.payload["pk"] == "3300000000000000132"
    assert record.raw_capture.payload["referenced_media"]["pk"] == "3300000000000000131"
    assert record.raw_capture.metadata["preservation"] == "exact-or-durable-reference"
    assert record.analysis == {}
    assert record.intermediate.asr == []
    assert record.intermediate.ocr == []
    assert record.intermediate.frames == []
    assert record.intermediate.frame_analysis == []


def test_instagram_browser_capture_is_idempotent_and_analysis_handoff_compatible(tmp_path) -> None:
    record = _canonical_record()
    raw_ref = record.raw_capture.ref or ""

    store = CollectionStore(tmp_path / "collection")
    payload = record.model_dump(mode="json")
    assert store.upsert_post(payload, raw_ref) is True
    assert store.upsert_post(payload, raw_ref) is False
    assert store.seen_count("instagram") == 1

    handoff = build_handoff(
        payload,
        project_id="synthetic",
        media_states=[{"media_index": 0, "status": "completed"}],
    )
    assert handoff["contract_version"] == "1.0"
    assert handoff["source_url"] == record.source_url
    assert handoff["status"] == "ready"
    store.close()


def test_instagram_fixture_is_public_safe_and_contains_no_session_material() -> None:
    serialized = json.dumps(fx.PHASE1_REEL_RESPONSE, sort_keys=True).casefold()
    for forbidden in (
        "cookie",
        "authorization",
        "access_token",
        "password",
        "sessionid",
        "csrftoken",
    ):
        assert forbidden not in serialized
    assert "example.invalid" in serialized
    assert "synthetic" in serialized


def test_instagram_capture_boundary_rejects_non_loopback_bind() -> None:
    with pytest.raises(ValueError, match="localhost"):
        CaptureServer(
            study_config="does-not-need-to-exist.yaml",
            data_root="does-not-need-to-exist",
            host="0.0.0.0",
            port=0,
        )


def test_browser_payload_decode_errors_are_explicit() -> None:
    with pytest.raises(ValueError, match="not text or JSON"):
        _decode_platform_body(132)
    with pytest.raises(json.JSONDecodeError):
        _decode_platform_body("{not-json")


def test_instagram_parser_does_not_guess_records_from_unsupported_payload() -> None:
    handler = Handler.__new__(Handler)
    rows = handler._records_for(
        "instagram",
        {"status": "ok", "items": [{"unrelated": True}]},
        "https://www.instagram.com/api/v1/feed/timeline/",
        "https://www.instagram.com/synthetic_phase1_ig/",
        {
            "captured_at": "2026-09-20T12:00:00Z",
            "source_platform_url": "https://www.instagram.com/synthetic_phase1_ig/",
            "source_url": "https://www.instagram.com/api/v1/feed/timeline/",
        },
        "raw/instagram/unsupported.ndjson",
    )
    assert rows == []
