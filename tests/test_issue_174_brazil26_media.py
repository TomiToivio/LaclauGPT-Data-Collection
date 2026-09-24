from __future__ import annotations

import json
from pathlib import Path

from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.distributed_media_runner import run_distributed_media
from laclaugpt_data_collection.media import MediaDownloader


def _record(platform: str) -> dict:
    return {
        "collection_id": "brazil26",
        "source_url": f"https://{platform}.example.test/public/1",
        "source": {"platform": platform},
        "content": {
            "media_references": [
                {
                    "kind": "video",
                    "url": f"https://media.example.test/{platform}.mp4",
                    "media_index": 0,
                }
            ]
        },
        "provenance": [{"metadata": {"collection_id": "brazil26"}}],
    }


def test_local_brazil26_media_handles_three_platforms_idempotently(
    tmp_path: Path, monkeypatch
) -> None:
    normalized = tmp_path / "normalized"
    normalized.mkdir()
    records = [_record(platform) for platform in ("instagram", "x", "tiktok")]
    (normalized / "browser.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        MediaDownloader,
        "_fetch",
        lambda self, url: (f"video:{url}".encode(), "video/mp4"),
    )
    settings = Settings(
        _env_file=None,
        project_id="brazil26",
        data_root=tmp_path,
        object_backend="filesystem",
        record_backend="auto",
    )

    first = run_distributed_media(
        settings,
        study_config=tmp_path / "private-study.yaml",
        data_root=tmp_path,
        workers=1,
        limit=10,
        use_lock=True,
    )
    second = run_distributed_media(
        settings,
        study_config=tmp_path / "private-study.yaml",
        data_root=tmp_path,
        workers=1,
        limit=10,
        use_lock=True,
    )

    assert first["storage"] == "filesystem"
    assert first["queued"] == first["completed"] == 3
    assert first["failed"] == 0
    assert {path.parent.name for path in (tmp_path / "media").rglob("*.mp4")} == {
        "instagram",
        "x",
        "tiktok",
    }
    assert second["queued"] == second["completed"] == second["failed"] == 0
