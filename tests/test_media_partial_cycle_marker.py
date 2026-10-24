"""A media cycle that records failures must still emit its end marker.

``scripts/run_ai26_laskin_media.sh`` runs under ``set -euo pipefail`` and the
distributed media runner returns exit 1 whenever any media object failed (see
``distributed_media_runner.main``, ``return 0 if result["failed"] == 0 else 1``).
Before this fix the shell aborted at the runner invocation and the
``AI26 Laskin media end`` echo never ran, so a cycle that downloaded its media
normally read as a silently stopped stage. The same class of defect was repaired
for the collection wrapper in #217; the media wrapper never got the same
treatment.

Observed in production on Laskin: the 2026-10-23T00:30 cycle (failed: 1) and the
2026-10-23T05:30 cycle (failed: 2) both printed their summary line and then no
end marker at all.

These tests execute the real wrapper against a stubbed runner binary, following
``tests/test_issue_217_partial_tick_marker.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _setup_checkout(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Build a synthetic checkout holding the real media wrapper and a stub runner."""
    root = tmp_path / "canonical checkout"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "run_ai26_laskin_media.sh", scripts / "run_ai26_laskin_media.sh")

    bins = root / ".venv" / "bin"
    bins.mkdir(parents=True)
    stub = bins / "laclaugpt-distributed-media"
    stub.write_text(
        "#!/bin/bash\n"
        'printf "%s\\n" "$@" >> "$RUNNER_CALL_LOG"\n'
        'printf "%s\\n" \'{"attempted": 2, "completed": 1, "failed": 1}\'\n'
        'exit "${STUB_RUNNER_STATUS:-0}"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)

    config = root / "data" / "config"
    config.mkdir(parents=True)
    (config / "ai26.yaml").write_text("study: ai26\n", encoding="utf-8")
    env_file = tmp_path / "synthetic.env"
    env_file.write_text("", encoding="utf-8")

    env = {k: v for k, v in os.environ.items() if not k.startswith("LACLAUGPT_")}
    env.update(
        LACLAUGPT_ENV_FILE=str(env_file),
        LACLAUGPT_AI26_STUDY_CONFIG=str(config / "ai26.yaml"),
        LACLAUGPT_AI26_MEDIA_LOCK=str(root / "data" / "tmp" / "media.lock"),
        RUNNER_CALL_LOG=str(tmp_path / "runner.calls"),
    )
    return root, env


def _run(tmp_path: Path, status: int) -> tuple[subprocess.CompletedProcess[str], Path]:
    root, env = _setup_checkout(tmp_path)
    env["STUB_RUNNER_STATUS"] = str(status)
    result = subprocess.run(
        ["bash", str(root / "scripts" / "run_ai26_laskin_media.sh")],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, Path(env["RUNNER_CALL_LOG"])


def test_failed_media_cycle_emits_end_marker_and_propagates_status(tmp_path: Path) -> None:
    """A cycle with media failures must still log its end marker, and still fail."""
    result, _ = _run(tmp_path, status=1)

    assert "AI26 Laskin media start" in result.stdout
    assert "AI26 Laskin media end" in result.stdout
    assert "runner_status=1" in result.stdout
    assert result.returncode == 1


def test_clean_media_cycle_emits_end_marker_and_succeeds(tmp_path: Path) -> None:
    """A clean cycle keeps the plain end marker and exits 0."""
    result, _ = _run(tmp_path, status=0)

    assert "AI26 Laskin media start" in result.stdout
    assert "AI26 Laskin media end" in result.stdout
    assert "runner_status" not in result.stdout
    assert result.returncode == 0


def test_media_runner_really_runs_before_the_end_marker(tmp_path: Path) -> None:
    """The runner is invoked, and the end marker is emitted after it, not before."""
    result, call_log = _run(tmp_path, status=1)

    assert call_log.exists(), "the runner stub was never invoked"
    assert "--study-config" in call_log.read_text(encoding="utf-8")
    lines = result.stdout.splitlines()
    start = next(i for i, line in enumerate(lines) if line.endswith("AI26 Laskin media start"))
    end = next(i for i, line in enumerate(lines) if "AI26 Laskin media end" in line)
    assert start < end
