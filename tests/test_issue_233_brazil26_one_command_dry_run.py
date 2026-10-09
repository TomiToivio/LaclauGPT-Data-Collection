"""Issue #233 acceptance coverage: the one-command start and its dry-run.

These tests are offline by design. They assert the *wiring* of the researcher's
single startup command and, above all, that ``--dry-run`` starts nothing: no
backend, no Firefox, no crontab write. CI cannot reach CSC Allas, MongoDB or a
live Firefox profile, so the dry-run is exactly the part that must be provable
without them.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from laclaugpt_data_collection import brazil26_browser as b26

ROOT = Path(__file__).resolve().parents[1]

_STUDY = """\
study: brazil26
title: synthetic dry-run fixture
timezone: America/Sao_Paulo
window:
  start: 2026-09-01
  end: 2026-10-10
collection_policy:
  preserve_source_url: true
"""

_MANIFEST_THREE = 'enabled_platforms = ["x", "instagram", "tiktok"]\n'


def _checkout(tmp_path: Path, *, study_text: str = _STUDY) -> Path:
    """A synthetic checkout with a valid study, extension manifest and data root."""
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "data/config").mkdir(parents=True)
    (root / "browser/firefox").mkdir(parents=True)
    (root / "browser/firefox/manifest.json").write_text("{}\n", encoding="utf-8")
    (root / "data/config/brazil26.yaml").write_text(study_text, encoding="utf-8")
    (root / "data/config/brazil26.sources.toml").write_text(_MANIFEST_THREE, encoding="utf-8")
    return root


def _env_file(root: Path, extra: str = "") -> Path:
    env_file = root / "data/config/brazil26-localhost.env"
    env_file.write_text(
        "LACLAUGPT_PROJECT_ID=brazil26\n"
        f"LACLAUGPT_SOURCE_MANIFEST={root / 'data/config/brazil26.sources.toml'}\n"
        + extra,
        encoding="utf-8",
    )
    return env_file


@pytest.fixture(autouse=True)
def _no_ambient_laclaugpt(monkeypatch: pytest.MonkeyPatch) -> None:
    """The browser runtime reads os.environ directly; never inherit the operator's."""
    for name in [n for n in os.environ if n.startswith("LACLAUGPT_")]:
        monkeypatch.delenv(name, raising=False)


def _run_dry(capsys: pytest.CaptureFixture[str], root: Path, **kwargs: Any) -> tuple[int, dict[str, Any]]:
    params: dict[str, Any] = dict(
        study_config=str(root / "data/config/brazil26.yaml"),
        data_root=str(root / "data"),
        repo_root=root,
        install_cron=False,
        launch_browser=False,
    )
    params.update(kwargs)
    code = b26.run_dry_run(**params)
    return code, json.loads(capsys.readouterr().out)


# --------------------------------------------------------------------------- #
# The dry-run prints a plan and starts nothing
# --------------------------------------------------------------------------- #

def test_dry_run_reports_the_plan_without_starting_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _checkout(tmp_path)
    monkeypatch.setenv("LACLAUGPT_ENV_FILE", str(_env_file(root)))
    # Sabotage the real side effects: if the dry-run touches any of them, fail.
    monkeypatch.setattr(b26, "_ensure_cron", lambda **_: pytest.fail("dry-run wrote cron"))
    monkeypatch.setattr(b26.subprocess, "Popen", lambda *a, **k: pytest.fail("dry-run spawned a process"))

    code, plan = _run_dry(capsys, root)

    assert code == 0
    assert plan["dry_run"] is True
    assert plan["status"] == "ready"
    assert plan["project_id"] == "brazil26"
    assert plan["study"] == "brazil26"
    assert plan["backend_bind"] == "http://127.0.0.1:8765"
    assert plan["backend_argv"][1:4] == ["-m", "laclaugpt_data_collection.brazil26_browser", "backend"]
    assert plan["cron"] == {"action": "skip", "installer": str(root / "scripts/install_cron_brazil26.sh")}
    assert not (root / "data/.brazil26-session.json").exists()


def test_dry_run_cron_action_reflects_the_no_cron_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _checkout(tmp_path)
    monkeypatch.setenv("LACLAUGPT_ENV_FILE", str(_env_file(root)))
    code = b26.run_dry_run(
        study_config=str(root / "data/config/brazil26.yaml"),
        data_root=str(root / "data"),
        repo_root=root,
        install_cron=True,
        launch_browser=False,
    )
    plan = json.loads(capsys.readouterr().out)
    assert code == 0
    assert plan["cron"]["action"] == "install"


def test_dry_run_reports_the_resolved_firefox_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _checkout(tmp_path)
    browser = tmp_path / "firefox-stub"
    browser.write_text("#!/bin/sh\necho 'Mozilla Firefox 999'\n", encoding="utf-8")
    browser.chmod(0o755)
    monkeypatch.setenv("LACLAUGPT_ENV_FILE", str(_env_file(root)))
    monkeypatch.setenv("LACLAUGPT_FIREFOX_COMMAND", str(browser))
    monkeypatch.setenv("LACLAUGPT_FIREFOX_PROFILE", "Brazil26 Research")

    code, plan = _run_dry(capsys, root, launch_browser=True)

    assert code == 0
    assert plan["launch_browser"] is True
    assert plan["firefox_argv"] == [str(browser), "-P", "Brazil26 Research"]


def test_dry_run_reports_a_non_brazil_study_as_would_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _checkout(tmp_path, study_text="study: ai26\nwindow:\n  start: 2026-09-01\n  end: 2026-10-10\n")
    monkeypatch.setenv("LACLAUGPT_ENV_FILE", str(_env_file(root)))

    code, plan = _run_dry(capsys, root)

    assert code == 2
    assert plan["status"] == "would-fail"
    assert any("non-Brazil" in item for item in plan["problems"])


def test_dry_run_rejects_a_non_loopback_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _checkout(tmp_path)
    monkeypatch.setenv("LACLAUGPT_ENV_FILE", str(_env_file(root)))
    code, plan = _run_dry(capsys, root, host="0.0.0.0")
    assert code == 2
    assert any("loopback" in item for item in plan["problems"])


# --------------------------------------------------------------------------- #
# --distributed surfaces the Allas/Mongo requirements in the plan
# --------------------------------------------------------------------------- #

def test_dry_run_distributed_flags_missing_allas_and_mongo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _checkout(tmp_path)
    monkeypatch.setenv("LACLAUGPT_ENV_FILE", str(_env_file(root)))
    code, plan = _run_dry(capsys, root, distributed=True)
    assert code == 2
    joined = " ".join(plan["problems"])
    assert "LACLAUGPT_OBJECT_BACKEND=s3" in joined
    assert "LACLAUGPT_S3_BUCKET" in joined
    assert "LACLAUGPT_MONGODB_URI" in joined


def test_dry_run_distributed_is_ready_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _checkout(tmp_path)
    extra = (
        "LACLAUGPT_OBJECT_BACKEND=s3\n"
        "LACLAUGPT_S3_BUCKET=private-brazil26\n"
        "LACLAUGPT_RECORD_BACKEND=mongodb\n"
        "LACLAUGPT_MONGODB_URI=mongodb://example.invalid:27017/brazil26\n"
    )
    monkeypatch.setenv("LACLAUGPT_ENV_FILE", str(_env_file(root, extra)))
    code, plan = _run_dry(capsys, root, distributed=True)
    assert code == 0
    assert plan["status"] == "ready"
    assert plan["distributed_preflight"] is True
    assert plan["source_policy"]["enabled_platforms"] == ["instagram", "tiktok", "x"]


# --------------------------------------------------------------------------- #
# The CLI flag is wired to the same code path
# --------------------------------------------------------------------------- #

def test_cli_dry_run_flag_prints_the_plan_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _checkout(tmp_path)
    monkeypatch.setenv("LACLAUGPT_ENV_FILE", str(_env_file(root)))
    code = b26.main([
        "--dry-run", "--no-browser", "--no-cron",
        "--study-config", str(root / "data/config/brazil26.yaml"),
        "--data-root", str(root / "data"),
    ])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["dry_run"] is True


def test_cli_distributed_start_gates_on_preflight_before_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A distributed start must fail closed when Allas/Mongo are unset."""
    root = _checkout(tmp_path)
    monkeypatch.setenv("LACLAUGPT_ENV_FILE", str(_env_file(root)))
    monkeypatch.setattr(b26, "run_researcher_session", lambda **_: pytest.fail("started despite failing gate"))
    code = b26.main([
        "--distributed", "--no-browser", "--no-cron",
        "--study-config", str(root / "data/config/brazil26.yaml"),
        "--data-root", str(root / "data"),
    ])
    assert code == 2


# --------------------------------------------------------------------------- #
# The one-command shell wrapper
# --------------------------------------------------------------------------- #

def _wrapper_checkout(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "canonical checkout"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "scripts/start_brazil26_localhost.sh", scripts / "start_brazil26_localhost.sh")
    bins = root / ".venv/bin"
    bins.mkdir(parents=True)
    stub = bins / "laclaugpt-brazil26"
    stub.write_text('#!/bin/bash\nprintf "%s\\n" "$@" >> "$CALL_LOG"\n')
    stub.chmod(0o755)
    (root / "data/config").mkdir(parents=True)
    (root / "data/config/brazil26.yaml").write_text(_STUDY, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("LACLAUGPT_")}
    env["CALL_LOG"] = str(tmp_path / "calls")
    return root, env


def test_start_wrapper_passes_dry_run_and_resolved_paths(tmp_path: Path) -> None:
    root, env = _wrapper_checkout(tmp_path)
    env_file = root / "data/config/brazil26-localhost.env"
    env_file.write_text('BRAZIL26_CONFIG="data/config/brazil26.yaml"\n', encoding="utf-8")
    env["LACLAUGPT_ENV_FILE"] = str(env_file)

    subprocess.run(
        ["bash", str(root / "scripts/start_brazil26_localhost.sh"), "--dry-run"],
        cwd=tmp_path, env=env, check=True, capture_output=True, text=True,
    )
    calls = Path(env["CALL_LOG"]).read_text()
    assert "--dry-run" in calls
    assert "--study-config" in calls
    # The wrapper forwards the configured study path verbatim (relative paths are
    # resolved by the CLI against the checkout), matching install_cron_brazil26.sh.
    assert "brazil26.yaml" in calls


def test_start_wrapper_requires_the_runtime_env_for_a_real_start(tmp_path: Path) -> None:
    root, env = _wrapper_checkout(tmp_path)
    env["LACLAUGPT_ENV_FILE"] = str(tmp_path / "absent.env")
    result = subprocess.run(
        ["bash", str(root / "scripts/start_brazil26_localhost.sh")],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "missing runtime env" in result.stderr


def test_start_wrapper_dry_run_works_without_the_runtime_env(tmp_path: Path) -> None:
    root, env = _wrapper_checkout(tmp_path)
    env["LACLAUGPT_ENV_FILE"] = str(tmp_path / "absent.env")
    subprocess.run(
        ["bash", str(root / "scripts/start_brazil26_localhost.sh"), "--dry-run"],
        cwd=tmp_path, env=env, check=True, capture_output=True, text=True,
    )
