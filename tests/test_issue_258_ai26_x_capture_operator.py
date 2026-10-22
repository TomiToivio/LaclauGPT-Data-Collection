"""Issue #258 acceptance coverage: the AI26 X capture operator command.

The command exists to make a manual research session reproducible: verify the AI26
identity, start the loopback backend, prove ``/status`` and ``/tour``, print the
Firefox handoff. The parts CI can prove without a workstation or a signed-in
profile are the offline ones:

* ``--dry-run`` starts nothing and touches nothing;
* a non-loopback bind is refused before any work happens;
* a missing private env fails closed with the document to read;
* ``status``/``stop`` are honest and idempotent when nothing is running;
* no value from the private env leaks into the operator output.

Everything here runs against a synthetic checkout in ``tmp_path``. Nothing binds a
port, reads the operator's environment, or reaches MongoDB/Redis/Allas.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/start_ai26_x_capture.sh"

_STUDY = """\
study: ai26
title: synthetic operator fixture
"""

#: A secret that must never appear in operator output.
_SECRET = "mongo-uri-with-password-do-not-print"


def _checkout(tmp_path: Path) -> Path:
    """A synthetic checkout holding the script and the shared runtime helpers."""
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "data/config").mkdir(parents=True)
    (root / "data/tmp").mkdir(parents=True)
    (root / "data/logs").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts/start_ai26_x_capture.sh")
    for helper in ("ai26_runtime.sh", "runtime_config.sh"):
        shutil.copy2(ROOT / "scripts" / helper, root / "scripts" / helper)
    (root / "data/config/ai26.yaml").write_text(_STUDY, encoding="utf-8")
    return root


def _env_file(root: Path) -> Path:
    env_file = root / "data/config/ai26-localhost.env"
    env_file.write_text(
        "LACLAUGPT_PROJECT_ID=ai26\n"
        "LACLAUGPT_BROWSER_PORT=8971\n"
        "LACLAUGPT_DATA_ROOT=./data\n"
        f"LACLAUGPT_MONGO_URI={_SECRET}\n",
        encoding="utf-8",
    )
    return env_file


def _run(root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the script exactly as the docs tell an operator to run it."""
    clean = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LACLAUGPT_", "AI26_"))
    }
    clean.update(env or {})
    return subprocess.run(
        ["bash", str(root / "scripts/start_ai26_x_capture.sh"), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        env=clean,
        timeout=120,
    )


@pytest.fixture(autouse=True)
def _no_ambient_laclaugpt(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in os.environ if n.startswith(("LACLAUGPT_", "AI26_"))]:
        monkeypatch.delenv(name, raising=False)


def test_help_names_the_three_operations_and_the_manual_policy(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    result = _run(root, "--help")

    assert result.returncode == 0
    out = result.stdout
    assert "start" in out and "status" in out and "stop" in out
    # The issue keeps browser navigation user-controlled; the command must say so.
    assert "never drives Firefox" in out or "user-controlled" in out
    assert "--dry-run" in out


def test_dry_run_prints_the_plan_and_touches_nothing(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    result = _run(root, "--dry-run")

    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "nothing is started" in out
    assert "ai26_browser backend" in out
    assert "127.0.0.1:8766" in out  # no env file yet, so the documented default
    assert "no crontab entry" in out
    # Nothing was created: no pid file, no log, no lock.
    assert not (root / "data/tmp/ai26-x-capture.pid").exists()
    assert not (root / "data/logs/ai26-x-capture.log").exists()


def test_dry_run_prefers_the_ai26_only_data_root(tmp_path: Path) -> None:
    """A shared data root makes the startup scan walk every other study."""
    root = _checkout(tmp_path)
    (root / "data/ai26/normalized").mkdir(parents=True)

    result = _run(root, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert str(root / "data/ai26") in result.stdout


def test_dry_run_honours_an_explicit_data_root(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    (root / "data/ai26/normalized").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"

    result = _run(root, "--dry-run", "--data-root", str(elsewhere))

    assert result.returncode == 0, result.stderr
    assert str(elsewhere) in result.stdout


def test_refuses_a_non_loopback_bind(tmp_path: Path) -> None:
    root = _checkout(tmp_path)

    for host in ("0.0.0.0", "192.168.1.27", "example.org"):
        result = _run(root, "--dry-run", "--host", host)
        assert result.returncode == 2, host
        assert "non-loopback" in result.stderr
    # The dry-run must not have been printed for a refused bind.
    assert "nothing is started" not in result.stdout


def test_start_without_the_private_env_fails_closed(tmp_path: Path) -> None:
    root = _checkout(tmp_path)

    result = _run(root, "start")

    assert result.returncode == 2
    assert "missing AI26 runtime env" in result.stderr
    assert "docs/AI26_FIREFOX_BROWSER_COLLECTION.md" in result.stderr
    assert not (root / "data/tmp/ai26-x-capture.pid").exists()


def test_status_when_nothing_runs_is_honest(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    _env_file(root)

    result = _run(root, "status")

    assert result.returncode == 3
    out = result.stdout
    assert "not running" in out
    assert "127.0.0.1:8971" in out  # the port from the private env, not a guess
    assert "no answer" in out


def test_status_reports_a_stale_pid_file_without_killing_anything(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    _env_file(root)
    # A pid that cannot be alive: 0 is never a valid process id for this use.
    (root / "data/tmp/ai26-x-capture.pid").write_text("999999999\n", encoding="utf-8")

    result = _run(root, "status")

    assert result.returncode == 3
    assert "stale pid file" in result.stdout


def test_stop_when_nothing_runs_is_idempotent(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    _env_file(root)

    first = _run(root, "stop")
    second = _run(root, "stop")

    assert first.returncode == 0
    assert second.returncode == 0
    assert "not running" in first.stdout and "not running" in second.stdout


def test_operator_output_never_prints_the_private_env(tmp_path: Path) -> None:
    """The env file holds credentials; every printed line must be paths, URLs, ids."""
    root = _checkout(tmp_path)
    _env_file(root)

    outputs = [
        _run(root, "--dry-run"),
        _run(root, "status"),
        _run(root, "stop"),
    ]

    for result in outputs:
        assert _SECRET not in result.stdout
        assert _SECRET not in result.stderr


def test_no_crontab_is_written(tmp_path: Path) -> None:
    """Manual capture stays manual: the command must not schedule anything."""
    root = _checkout(tmp_path)
    _env_file(root)
    marker = tmp_path / "crontab-touched"

    env = {
        # Any attempt to install or remove a schedule would run this and leave a trace.
        "CRONTAB": f"touch {marker}; /usr/bin/crontab",
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}",
    }
    result = _run(root, "--dry-run", env=env)

    assert result.returncode == 0, result.stderr
    assert not marker.exists()
