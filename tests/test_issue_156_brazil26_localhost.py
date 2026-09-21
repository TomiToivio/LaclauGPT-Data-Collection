from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from laclaugpt_data_collection import brazil26_browser


def test_preflight_accepts_local_only_profile(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = tmp_path / "repo"
    (repo / "browser/firefox").mkdir(parents=True)
    (repo / "browser/firefox/manifest.json").write_text("{}", encoding="utf-8")
    (repo / "data/config").mkdir(parents=True)
    (repo / "data/config/brazil26-localhost.env").write_text(
        "LACLAUGPT_PROJECT_ID=brazil26\n"
        "LACLAUGPT_RECORD_BACKEND=auto\n"
        "LACLAUGPT_OBJECT_BACKEND=filesystem\n"
        "LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND=local\n",
        encoding="utf-8",
    )
    config = tmp_path / "brazil.yaml"
    config.write_text("study: brazil26\n", encoding="utf-8")
    monkeypatch.setattr(
        brazil26_browser,
        "load_config",
        lambda _path: SimpleNamespace(study="brazil26"),
    )
    monkeypatch.setenv("LACLAUGPT_ENV_FILE", str(repo / "data/config/brazil26-localhost.env"))

    assert brazil26_browser.run_preflight(
        study_config=config,
        data_root=repo / "data",
        require_browser=False,
        repo_root=repo,
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["project_id"] == "brazil26"
    assert payload["distributed_requested"] is False


def test_validate_accepts_canonical_local_jsonl(tmp_path: Path, capsys) -> None:
    normalized = tmp_path / "normalized"
    normalized.mkdir()
    (normalized / "browser.jsonl").write_text(
        json.dumps({"source_url": "https://example.test/post/1", "collection_id": "brazil26"})
        + "\n",
        encoding="utf-8",
    )

    assert brazil26_browser.run_validate(data_root=tmp_path) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["records_checked"] == 1
    assert payload["status"] == "ok"


def test_validate_rejects_cross_study_row(tmp_path: Path, capsys) -> None:
    normalized = tmp_path / "normalized"
    normalized.mkdir()
    (normalized / "mixed.jsonl").write_text(
        json.dumps({"source_url": "https://example.test/post/1", "collection_id": "ai26"})
        + "\n",
        encoding="utf-8",
    )

    assert brazil26_browser.run_validate(data_root=tmp_path) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "invalid"
    assert "cross-study" in payload["errors"][0]


def test_stop_uses_session_pid(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / ".brazil26-session.json").write_text(
        json.dumps({"pid": 4321, "project_id": "brazil26"}),
        encoding="utf-8",
    )
    called: list[tuple[int, int]] = []
    monkeypatch.setattr(brazil26_browser.os, "kill", lambda pid, sig: called.append((pid, sig)))

    assert brazil26_browser.run_stop(data_root=tmp_path) == 0
    assert called and called[0][0] == 4321
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "stopping"


def test_backend_skips_distributed_mirror_for_local_profile(tmp_path: Path, monkeypatch) -> None:
    class Store:
        def seen_count(self) -> int:
            return 0

        def write_manifest(self, payload: dict) -> None:
            assert payload["distributed_enabled"] is False

        def close(self) -> None:
            pass

    class Server:
        def __init__(self, *_args, **_kwargs) -> None:
            self.cfg = SimpleNamespace(study="brazil26")
            self.stats = {}
            self.store = Store()

        def serve_forever(self) -> None:
            return None

        def server_close(self) -> None:
            pass

    class NoMirror:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("distributed mirror must not start in local-only mode")

    monkeypatch.setattr(brazil26_browser, "_ensure_brazil26_study", lambda _path: "brazil26")
    monkeypatch.setattr(
        brazil26_browser,
        "_brazil26_settings",
        lambda: SimpleNamespace(
            project_id="brazil26",
            run_id="test",
            distributed_requested=False,
        ),
    )
    monkeypatch.setattr(brazil26_browser, "CaptureServer", Server)
    monkeypatch.setattr(brazil26_browser, "JsonlDistributedMirror", NoMirror)

    assert brazil26_browser.run_backend(
        study_config="private.yaml",
        data_root=str(tmp_path),
        host="127.0.0.1",
        port=8765,
        sync_interval=1.0,
    ) == 0
