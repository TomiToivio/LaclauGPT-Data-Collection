"""Synthetic multi-host X capture regression: no live services or credentials."""
from __future__ import annotations

import json
from pathlib import Path

import mongomock
import pytest

from laclaugpt_data_collection import ai26_browser
from laclaugpt_data_collection.config import Settings


def test_two_mirrors_share_text_ready_mongo_without_allas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = mongomock.MongoClient()
    monkeypatch.setattr("pymongo.MongoClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(
        "laclaugpt_data_collection.distributed_capture.S3ObjectStore",
        lambda **kwargs: pytest.fail("text-only mirror must not instantiate S3"),
    )
    private = tmp_path / "private"
    private.mkdir()
    study = private / "ai26.yaml"
    study.write_text("study: ai26\nwindow: {start: 2026-09-01, end: 2026-12-31}\n")
    row = {
        "collection_id": "ai26",
        "arena": "elites",
        "source_url": "https://x.com/synthetic/status/123",
        "source_native_ids": {"platform_post_id": "123"},
        "source": {"platform": "x", "author": "synthetic", "created_at": "2026-09-02T00:00:00Z"},
        "content": {
            "text": "Synthetic research text",
            "media_references": [{"kind": "image", "url": "https://example.invalid/image"}],
        },
        "raw_capture": {"payload": {"id": "123", "text": "Synthetic research text"}},
    }
    records = client["synthetic"]["ai26__records"]
    first_key = None
    for host in ("laptop", "custom"):
        root = tmp_path / host
        normalized = root / "normalized"
        normalized.mkdir(parents=True)
        host_row = dict(row)
        if host == "custom":
            host_row["source_url"] = "https://twitter.com/synthetic/status/123?s=20"
        (normalized / "x.jsonl").write_text(json.dumps(host_row) + "\n")
        settings = Settings(
            _env_file=None,
            project_id="ai26",
            run_id=f"fixture-{host}",
            machine=host,
            record_backend="mongodb",
            mongodb_uri="mongodb://example.invalid",
            mongodb_database="synthetic",
            private_config_dir=private,
        )
        mirror = ai26_browser.JsonlDistributedMirror(
            settings, study_config=study, data_root=root
        )
        assert mirror.scan_once() == {"scanned": 1, "synced": 1, "rejected": 0}
        assert mirror.scan_once()["scanned"] == 0
        assert records.count_documents({}) == 1
        stored = records.find_one()
        assert stored["handoff"]["status"] == "ready"
        assert stored["content"]["media_references"] == []
        assert stored["source"]["raw_metadata"]["deferred_media_references"]
        assert stored["raw_capture"]["payload"]["id"] == "123"
        if first_key is None:
            first_key = stored["handoff"]["handoff_key"]
            records.update_one({}, {"$set": {"analysis": {"synthetic": "completed"}}})
        else:
            assert stored["handoff"]["handoff_key"] == first_key
            assert stored["analysis"] == {"synthetic": "completed"}
            assert {p["metadata"]["machine"] for p in stored["provenance"]} == {
                "laptop", "custom",
            }


def test_browser_preflight_refuses_local_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    study = tmp_path / "ai26.yaml"
    study.write_text("study: ai26\nwindow: {start: 2026-09-01, end: 2026-12-31}\n")
    monkeypatch.setattr(ai26_browser, "_ai26_settings", lambda: Settings(_env_file=None))
    with pytest.raises(ValueError, match="shared MongoDB"):
        ai26_browser.run_check(study_config=str(study))


def test_text_browser_settings_disable_inline_media_and_allas(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        ai26_browser, "_ai26_settings",
        lambda: Settings(_env_file=None, object_backend="s3", capture_media_inline=True),
    )
    settings = ai26_browser._text_browser_settings()
    assert settings.object_backend == "filesystem"
    assert settings.capture_media_inline is False
