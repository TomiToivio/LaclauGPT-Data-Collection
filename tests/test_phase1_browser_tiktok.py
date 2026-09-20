"""Phase 1 browser/TikTok vertical-slice contract for issue #105."""
from __future__ import annotations

from laclaugpt_data_collection.capture_server import CaptureServer, Handler
from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.models import CanonicalRecord
from laclaugpt_data_collection.store import CollectionStore


def _tiktok_payload() -> dict:
    return {
        "itemList": [
            {
                "id": "7300000000000000105",
                "desc": "Synthetic Phase 1 TikTok fixture",
                "createTime": "1789898400",
                "author": {
                    "uniqueId": "synthetic_phase1",
                    "nickname": "Synthetic Researcher",
                },
                "duetInfo": {"duetFromId": "7300000000000000004"},
                "stats": {
                    "diggCount": 12,
                    "commentCount": 3,
                    "shareCount": 2,
                    "playCount": 99,
                },
            }
        ]
    }


def _canonical_record() -> CanonicalRecord:
    handler = Handler.__new__(Handler)
    api_url = "https://www.tiktok.com/api/post/item_list/?aid=1988"
    platform_url = "https://www.tiktok.com/@synthetic_phase1"
    meta = {
        "captured_at": "2026-09-20T08:00:00Z",
        "capture_id": "synthetic-browser-capture-105",
        "collector_version": "test",
        "git_commit": "test",
        "source_platform_url": platform_url,
        "source_url": api_url,
        "run_id": "issue-105-test",
        "study": "synthetic",
        "account": "synthetic",
    }
    rows = handler._records_for(
        "tiktok",
        _tiktok_payload(),
        api_url,
        platform_url,
        meta,
        "raw/tiktok/synthetic-105.ndjson",
    )
    assert len(rows) == 1
    return CanonicalRecord.model_validate(rows[0])


def test_tiktok_browser_capture_reaches_canonical_record_with_native_relationship() -> None:
    record = _canonical_record()

    assert record.source.platform == "tiktok"
    assert record.source_url == (
        "https://www.tiktok.com/@synthetic_phase1/video/7300000000000000105"
    )
    assert record.source_native_ids["document_id"] == "7300000000000000105"
    assert record.source_native_ids["parent_document_id"] == "7300000000000000004"
    assert record.source.raw_metadata["parent_document_id"] == "7300000000000000004"
    assert record.raw_capture.ref == "raw/tiktok/synthetic-105.ndjson"
    assert record.raw_capture.payload["id"] == "7300000000000000105"
    assert record.analysis == {}


def test_tiktok_browser_capture_is_idempotent_and_analysis_handoff_compatible(tmp_path) -> None:
    record = _canonical_record()
    raw_ref = record.raw_capture.ref or ""

    store = CollectionStore(tmp_path / "collection")
    payload = record.model_dump(mode="json")
    assert store.upsert_post(payload, raw_ref) is True
    assert store.upsert_post(payload, raw_ref) is False
    assert store.seen_count("tiktok") == 1

    handoff = build_handoff(payload, project_id="synthetic")
    assert handoff["contract_version"] == "1.0"
    assert handoff["source_url"] == record.source_url
    assert handoff["status"] == "ready"
    store.close()


def test_capture_server_rejects_non_loopback_bind_before_socket_or_network_use() -> None:
    try:
        CaptureServer(
            study_config="does-not-need-to-exist.yaml",
            data_root="does-not-need-to-exist",
            host="0.0.0.0",
            port=0,
        )
    except ValueError as exc:
        assert "localhost" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-loopback browser capture bind must be rejected")
