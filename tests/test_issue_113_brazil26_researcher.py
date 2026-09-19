from __future__ import annotations

from pathlib import Path

import pytest

from laclaugpt_data_collection import brazil26_browser


def test_resolve_explicit_private_config(tmp_path: Path) -> None:
    config = tmp_path / "brazil-election-2026.yaml"
    config.write_text("study: brazil26\n", encoding="utf-8")
    assert brazil26_browser._resolve_study_config(config) == config.resolve()


def test_resolve_default_private_repo_config(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "LaclauGPT-Data-Collection"
    repo.mkdir()
    private = tmp_path / "LaclauGPT-Private" / "collection" / "brazil26"
    private.mkdir(parents=True)
    config = private / "brazil-election-2026.yaml"
    config.write_text("study: brazil26\n", encoding="utf-8")
    monkeypatch.delenv("BRAZIL26_CONFIG", raising=False)
    monkeypatch.delenv("LACLAUGPT_STUDY_CONFIG", raising=False)
    monkeypatch.delenv("LACLAUGPT_PRIVATE_REPO", raising=False)

    assert brazil26_browser._resolve_study_config(repo_root=repo) == config.resolve()


def test_missing_private_config_fails_without_demo_fallback(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "LaclauGPT-Data-Collection"
    repo.mkdir()
    monkeypatch.delenv("BRAZIL26_CONFIG", raising=False)
    monkeypatch.delenv("LACLAUGPT_STUDY_CONFIG", raising=False)
    monkeypatch.delenv("LACLAUGPT_PRIVATE_REPO", raising=False)

    with pytest.raises(FileNotFoundError, match="brazil-election-2026.yaml"):
        brazil26_browser._resolve_study_config(repo_root=repo)


def test_session_environment_forces_brazil26_identity(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = tmp_path / "private.yaml"
    config.write_text("study: brazil26\n", encoding="utf-8")
    data_root = tmp_path / "existing-data"
    env_file = tmp_path / "runtime.env"
    env_file.write_text(
        "LACLAUGPT_PROJECT_ID=ai26\n"
        "LACLAUGPT_BROWSER=firefox-local\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LACLAUGPT_PROJECT_ID", "ai26")

    env = brazil26_browser._session_environment(
        repo_root=repo,
        study_config=config,
        data_root=data_root,
        env_file=env_file,
    )

    assert env["LACLAUGPT_PROJECT_ID"] == "brazil26"
    assert env["LACLAUGPT_STUDY_CONFIG"] == str(config)
    assert env["BRAZIL26_CONFIG"] == str(config)
    assert env["LACLAUGPT_DATA_ROOT"] == str(data_root)
    assert env["LACLAUGPT_BROWSER"] == "firefox-local"


def test_firefox_command_supports_dedicated_profile(monkeypatch) -> None:
    monkeypatch.setattr(brazil26_browser.shutil, "which", lambda name: "/usr/bin/firefox")
    command = brazil26_browser._firefox_command(
        {"LACLAUGPT_FIREFOX_PROFILE": "Brazil26 Research"}
    )
    assert command == ["/usr/bin/firefox", "-P", "Brazil26 Research"]


def test_no_subcommand_is_researcher_session(monkeypatch) -> None:
    called: dict[str, object] = {}

    def fake_run(**kwargs: object) -> int:
        called.update(kwargs)
        return 0

    monkeypatch.setattr(brazil26_browser, "run_researcher_session", fake_run)
    assert brazil26_browser.main(["--no-browser", "--no-cron"]) == 0
    assert called["launch_browser"] is False
    assert called["install_cron"] is False


def test_mirror_rejects_cross_study_record(tmp_path: Path, monkeypatch) -> None:
    from laclaugpt_data_collection.config import Settings

    class Sink:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        def assert_private_config(self, study_config: str | Path) -> Path:
            return Path(study_config)

        def ingest(self, record: dict) -> dict:
            return record

    monkeypatch.setattr(brazil26_browser, "DistributedCaptureSink", Sink)
    normalized = tmp_path / "normalized"
    normalized.mkdir()
    (normalized / "mixed.jsonl").write_text(
        '{"collection_id":"ai26","source_url":"https://example.test/a"}\n',
        encoding="utf-8",
    )
    mirror = brazil26_browser.JsonlDistributedMirror(
        Settings(project_id="brazil26", run_id="test"),
        study_config="private.yaml",
        data_root=tmp_path,
    )

    with pytest.raises(ValueError, match="refuses collection_id='ai26'"):
        mirror.scan_once()


def test_brazil26_cron_is_marker_managed_private_and_locked() -> None:
    root = Path(__file__).resolve().parents[1]
    cron = (root / "scripts/install_cron_brazil26.sh").read_text(encoding="utf-8")
    media = (root / "scripts/run_brazil26_localhost_media.sh").read_text(encoding="utf-8")

    assert "# BEGIN LACLAUGPT BRAZIL26" in cron
    assert "# END LACLAUGPT BRAZIL26" in cron
    assert "brazil-election-2026.yaml" in cron
    assert "*/15 * * * *" in cron
    assert "LACLAUGPT_STUDY_CONFIG=" in cron
    assert "run_brazil26_localhost_media.sh" in cron
    assert "--lock" in media
    assert "brazil-election-2026.yaml" in media
