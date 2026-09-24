"""Offline regression coverage for the Brazil26 15-minute local media worker."""
from __future__ import annotations

from pathlib import Path

import pytest

from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection import distributed_media_runner as runner
from laclaugpt_data_collection.media import MediaDownloader


def _record(platform: str) -> dict:
    return {
        "collection_id": "brazil26",
        "source_url": f"https://{platform}.example.invalid/public/1",
        "source": {"platform": platform},
        "content": {"media_references": [
            {"media_index": 0, "kind": "video", "url": f"https://cdn.example.invalid/{platform}.mp4"}
        ]},
    }


def test_local_profile_downloads_three_platforms_without_remote_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "private.yaml"
    config.write_text("study: brazil26\n", encoding="utf-8")
    records = [_record(name) for name in ("instagram", "x", "tiktok")]
    records.append({**_record("x"), "collection_id": "ai26"})
    monkeypatch.setattr(runner, "load_records", lambda _root: records)

    def forbidden_remote(*_args, **_kwargs):
        raise AssertionError("local profile must not initialize MongoDB/S3")

    monkeypatch.setattr(runner, "DistributedCaptureSink", forbidden_remote)
    monkeypatch.setattr(runner, "S3ObjectStore", forbidden_remote)
    requested: list[str] = []

    def fake_fetch(self: MediaDownloader, url: str) -> tuple[bytes, str]:
        requested.append(url)
        return b"synthetic video", "video/mp4"

    monkeypatch.setattr(MediaDownloader, "_fetch", fake_fetch)
    settings = Settings(project_id="brazil26", _env_file=None)
    first = runner.run_distributed_media(
        settings, study_config=config, data_root=tmp_path, workers=1, limit=10, use_lock=True
    )
    assert first["storage"] == "filesystem"
    assert first["records_scanned"] == 3
    assert first["completed"] == 3
    assert first["mongo_refreshed"] == 0
    assert len(requested) == 3
    assert len(list((tmp_path / "media").rglob("*.mp4"))) == 3

    second = runner.run_distributed_media(
        settings, study_config=config, data_root=tmp_path, workers=1, limit=10, use_lock=True
    )
    assert second["queued"] == 0
    assert second["completed"] == 0
    assert len(requested) == 3


def test_local_media_still_requires_private_study(tmp_path: Path) -> None:
    settings = Settings(project_id="brazil26", _env_file=None)
    with pytest.raises(FileNotFoundError, match="Private study configuration"):
        runner.run_distributed_media(
            settings,
            study_config=tmp_path / "missing.yaml",
            data_root=tmp_path,
            use_lock=False,
        )
