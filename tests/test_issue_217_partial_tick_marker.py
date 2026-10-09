"""Issue #217: a partial collection tick must still emit its end marker.

The wrapper ``scripts/run_ai26_laskin_collect.sh`` runs under ``set -euo pipefail``
and the runner returns exit 1 whenever any source recorded an error (``status:
partial``). Before the fix the shell therefore aborted at the runner invocation
and the ``AI26 Laskin collection end`` echo never ran, so a tick that collected its
records normally read as a silently stopped stage.

These tests execute the real wrapper against stubbed runner binaries, following the
existing wrapper-execution pattern in ``tests/test_issue_194_brazil26_wrappers.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _setup_checkout(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Build a synthetic checkout holding the real collect wrapper and a stub runner."""
    root = tmp_path / "canonical checkout"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "run_ai26_laskin_collect.sh", scripts / "run_ai26_laskin_collect.sh")

    bins = root / ".venv" / "bin"
    bins.mkdir(parents=True)
    stub = bins / "python"
    stub.write_text(
        "#!/bin/bash\n"
        'printf "%s\\n" "$@" >> "$RUNNER_CALL_LOG"\n'
        'exit "${STUB_RUNNER_STATUS:-0}"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)

    config = root / "data" / "config"
    config.mkdir(parents=True)
    (config / "ai26.yaml").write_text("study: ai26\n", encoding="utf-8")
    (config / "ai26.sources.toml").write_text("# synthetic manifest\n", encoding="utf-8")
    env_file = tmp_path / "synthetic.env"
    env_file.write_text("", encoding="utf-8")

    env = {k: v for k, v in os.environ.items() if not k.startswith("LACLAUGPT_")}
    env.update(
        LACLAUGPT_ENV_FILE=str(env_file),
        LACLAUGPT_AI26_STUDY_CONFIG=str(config / "ai26.yaml"),
        LACLAUGPT_AI26_SOURCE_MANIFEST=str(config / "ai26.sources.toml"),
        LACLAUGPT_AI26_COLLECT_LOCK=str(root / "data" / "tmp" / "collect.lock"),
        RUNNER_CALL_LOG=str(tmp_path / "runner.calls"),
    )
    return root, env


def _run(tmp_path: Path, status: int) -> tuple[subprocess.CompletedProcess[str], Path]:
    root, env = _setup_checkout(tmp_path)
    env["STUB_RUNNER_STATUS"] = str(status)
    result = subprocess.run(
        ["bash", str(root / "scripts" / "run_ai26_laskin_collect.sh")],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, Path(env["RUNNER_CALL_LOG"])


def test_partial_tick_emits_end_marker_and_propagates_status(tmp_path: Path) -> None:
    """A partial tick (runner exit 1) must still log its end marker, and still fail."""
    result, _ = _run(tmp_path, status=1)

    assert "AI26 Laskin collection start" in result.stdout
    assert "AI26 Laskin collection end" in result.stdout
    assert "runner_status=1" in result.stdout
    assert result.returncode == 1


def test_clean_tick_emits_end_marker_and_succeeds(tmp_path: Path) -> None:
    """A clean tick keeps the plain end marker and exits 0."""
    result, _ = _run(tmp_path, status=0)

    assert "AI26 Laskin collection start" in result.stdout
    assert "AI26 Laskin collection end" in result.stdout
    assert "runner_status=0" in result.stdout
    assert result.returncode == 0


def test_runner_really_runs_before_the_end_marker(tmp_path: Path) -> None:
    """The runner is invoked, and the end marker is emitted after it, not before."""
    result, call_log = _run(tmp_path, status=1)

    assert call_log.exists(), "the runner stub was never invoked"
    assert "ai26_laskin_runner" in call_log.read_text(encoding="utf-8")
    lines = result.stdout.splitlines()
    start = next(i for i, line in enumerate(lines) if line.endswith("AI26 Laskin collection start"))
    end = next(i for i, line in enumerate(lines) if "AI26 Laskin collection end" in line)
    assert start < end
