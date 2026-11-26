"""AI26 X text remains available without downloading supplementary media."""
from copy import deepcopy

import pytest

from laclaugpt_data_collection.handoff import build_handoff, source_revision


def post():
    return {
        "project_id": "ai26",
        "collection_id": "ai26",
        "source_url": "https://x.com/synthetic/status/123",
        "source_native_ids": {"post_id": "123"},
        "source": {"platform": "x", "created_at": "2026-11-25T10:00:00Z"},
        "content": {
            "text": "Synthetic post about AI.",
            "media_references": [
                {"kind": "photo", "url": "https://example.invalid/photo.jpg"},
                {"kind": "video", "url": "https://example.invalid/video.mp4"},
            ],
        },
    }


def test_text_only_handoff_preserves_source_and_revision():
    record = post()
    before = deepcopy(record)
    envelope = build_handoff(record, project_id="ai26")
    assert envelope["status"] == "ready"
    assert envelope["reason"] == "ai26_x_text_only"
    assert envelope["revision"] == source_revision(before)
    assert envelope["handoff_key"] == build_handoff(record, run_id="another-host")["handoff_key"]
    assert record == before


@pytest.mark.parametrize("change", ["document", "unknown", "empty", "other_study", "other_platform"])
def test_required_media_still_blocks(change):
    record = post()
    if change in {"document", "unknown"}:
        record["content"]["media_references"][0]["kind"] = change
    elif change == "empty":
        record["content"]["text"] = " "
    elif change == "other_study":
        record["collection_id"] = "other"
    else:
        record["source"]["platform"] = "arxiv"
    assert build_handoff(record, project_id="ai26")["status"] == "waiting_media"


def test_publication_floor_still_excludes():
    record = post()
    record["source"]["created_at"] = "2026-08-31T10:00:00Z"
    assert build_handoff(record, project_id="ai26")["status"] == "excluded"


def test_bounded_repair_preserves_record_and_is_idempotent():
    import importlib.util
    from pathlib import Path

    import mongomock

    path = Path(__file__).resolve().parents[1] / "scripts/reconcile_ai26_x_text_handoffs.py"
    spec = importlib.util.spec_from_file_location("reconcile_x", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    collection = mongomock.MongoClient().synthetic.ai26__records
    record = post()
    record["handoff"] = {**build_handoff(record), "status": "waiting_media"}
    record["analysis"] = {"synthetic": "preserve"}
    collection.insert_one(record)
    original = collection.find_one()
    assert module.reconcile(collection, limit=1)["eligible"] == 1
    assert collection.find_one() == original
    assert module.reconcile(collection, limit=1, apply=True)["updated"] == 1
    after = collection.find_one()
    assert after["handoff"]["status"] == "ready"
    assert after["handoff"]["handoff_key"] == original["handoff"]["handoff_key"]
    assert {k: v for k, v in after.items() if k != "handoff"} == {
        k: v for k, v in original.items() if k != "handoff"
    }
    assert module.reconcile(collection, limit=1, apply=True)["updated"] == 0
