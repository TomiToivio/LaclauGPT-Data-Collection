from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from laclaugpt_data_collection import brazil26_browser
from laclaugpt_data_collection.config import Settings


class FakeSink:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.rows: list[dict] = []
        self.checked: str | None = None

    def assert_private_config(self, study_config: str | Path) -> Path:
        self.checked = str(study_config)
        return Path(study_config)

    def ingest(self, record: dict) -> dict:
        self.rows.append(record)
        return record

    def smoke_check(self) -> dict[str, str]:
        return {"project_id": self.settings.project_id, "redis": "ok"}


def test_brazil26_study_guard_accepts_brazil_alias(monkeypatch) -> None:
    monkeypatch.setattr(
        brazil26_browser,
        "load_config",
        lambda _path: SimpleNamespace(study="Brazil Election 2026"),
    )
    assert brazil26_browser._ensure_brazil26_study("private.yaml") == "Brazil Election 2026"


def test_brazil26_study_guard_rejects_other_study(monkeypatch) -> None:
    monkeypatch.setattr(
        brazil26_browser,
        "load_config",
        lambda _path: SimpleNamespace(study="AI26"),
    )
    with pytest.raises(ValueError, match="refuses non-Brazil"):
        brazil26_browser._ensure_brazil26_study("private.yaml")


def test_brazil26_settings_defaults_project_and_run_id(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "LACLAUGPT_PROJECT_ID=ai26\nLACLAUGPT_RUN_ID=ambient-dotenv\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("LACLAUGPT_PROJECT_ID", raising=False)
    monkeypatch.delenv("LACLAUGPT_RUN_ID", raising=False)

    settings = brazil26_browser._brazil26_settings(env_file=None)

    assert settings.project_id == "brazil26"
    assert settings.run_id.startswith("brazil26-browser-")


def test_brazil26_settings_ignore_conflicting_ambient_dotenv(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "LACLAUGPT_PROJECT_ID=ai26\n"
        "LACLAUGPT_RUN_ID=wrong-run\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LACLAUGPT_PROJECT_ID", raising=False)
    monkeypatch.delenv("LACLAUGPT_RUN_ID", raising=False)

    settings = brazil26_browser._brazil26_settings()

    assert settings.project_id == "brazil26"
    assert settings.run_id.startswith("brazil26-browser-")
    assert settings.run_id != "wrong-run"


def test_settings_can_still_load_an_explicit_dotenv(tmp_path) -> None:
    env_file = tmp_path / "explicit.env"
    env_file.write_text(
        "LACLAUGPT_PROJECT_ID=from-file\n"
        "LACLAUGPT_RUN_ID=explicit-run\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.project_id == "from-file"
    assert settings.run_id == "explicit-run"


def test_brazil26_settings_rejects_cross_study_namespace(monkeypatch) -> None:
    monkeypatch.setenv("LACLAUGPT_PROJECT_ID", "ai26")
    with pytest.raises(ValueError, match="must be 'brazil26'"):
        brazil26_browser._brazil26_settings(env_file=None)


def test_mirror_is_incremental_and_persists_collection_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(brazil26_browser, "DistributedCaptureSink", FakeSink)
    normalized = tmp_path / "normalized"
    normalized.mkdir()
    source = normalized / "x.jsonl"
    source.write_text(
        json.dumps({"source_url": "https://example.test/post/1"}) + "\n",
        encoding="utf-8",
    )
    settings = Settings(project_id="brazil26", run_id="test-run")
    mirror = brazil26_browser.JsonlDistributedMirror(
        settings,
        study_config="private.yaml",
        data_root=tmp_path,
        interval_seconds=0.1,
    )

    first = mirror.scan_once()
    second = mirror.scan_once()

    assert first == {"scanned": 1, "synced": 1}
    assert second == {"scanned": 0, "synced": 0}
    assert mirror.sink.rows[0]["collection_id"] == "brazil26"
    state = json.loads((tmp_path / ".brazil26-distributed-offsets.json").read_text())
    assert state["x.jsonl"] == source.stat().st_size


def test_mirror_retries_failed_line_without_advancing_offset(tmp_path, monkeypatch) -> None:
    class FlakySink(FakeSink):
        attempts = 0

        def ingest(self, record: dict) -> dict:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("temporary remote failure")
            return super().ingest(record)

    monkeypatch.setattr(brazil26_browser, "DistributedCaptureSink", FlakySink)
    normalized = tmp_path / "normalized"
    normalized.mkdir()
    source = normalized / "instagram.jsonl"
    source.write_text(
        json.dumps({"source_url": "https://example.test/post/2"}) + "\n",
        encoding="utf-8",
    )
    mirror = brazil26_browser.JsonlDistributedMirror(
        Settings(project_id="brazil26", run_id="test-run"),
        study_config="private.yaml",
        data_root=tmp_path,
    )

    with pytest.raises(RuntimeError, match="temporary remote failure"):
        mirror.scan_once()
    assert not mirror.state_path.exists()

    assert mirror.scan_once() == {"scanned": 1, "synced": 1}
    assert mirror.sink.rows[0]["source_url"] == "https://example.test/post/2"


def test_run_backend_rejects_non_loopback_before_remote_setup() -> None:
    with pytest.raises(ValueError, match="localhost/loopback"):
        brazil26_browser.run_backend(
            study_config="private.yaml",
            data_root="data/brazil26",
            host="0.0.0.0",
            port=8765,
            sync_interval=1.0,
        )
