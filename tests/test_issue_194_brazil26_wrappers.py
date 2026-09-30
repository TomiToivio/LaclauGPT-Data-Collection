"""Execute the cron wrappers with synthetic config and offline worker stubs."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def setup_checkout(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "canonical checkout"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "run_brazil26_localhost_collect.sh",
        "run_brazil26_localhost_sync.sh",
        "install_cron_brazil26.sh",
    ):
        shutil.copy(ROOT / "scripts" / name, scripts / name)
    bins = root / ".venv/bin"
    bins.mkdir(parents=True)
    for name in ("laclaugpt-server-rss", "laclaugpt-collect", "python"):
        stub = bins / name
        stub.write_text('#!/bin/bash\nprintf "%s\\n" "$@" >> "$CALL_LOG"\n')
        stub.chmod(0o755)
    config = root / "data/config"
    config.mkdir(parents=True)
    (config / "study.yaml").write_text("study_id: synthetic\n")
    (config / "approved.toml").write_text("# synthetic manifest\n")
    env_file = config / "custom.env"
    env_file.write_text(
        'BRAZIL26_CONFIG="data/config/study.yaml"\n'
        'LACLAUGPT_SOURCE_MANIFEST="data/config/approved.toml"\n'
        'LACLAUGPT_DATA_ROOT="data/selected"\n'
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("LACLAUGPT_")}
    env.update(
        LACLAUGPT_ENV_FILE=str(env_file),
        LACLAUGPT_RUN_ID="synthetic-run",
        CALL_LOG=str(tmp_path / "calls"),
    )
    return root, env


@pytest.mark.parametrize("worker", ["collect", "sync"])
def test_wrappers_load_env_paths_before_validating(tmp_path: Path, worker: str) -> None:
    root, env = setup_checkout(tmp_path)
    subprocess.run(
        ["bash", str(root / f"scripts/run_brazil26_localhost_{worker}.sh")],
        cwd=tmp_path, env=env, check=True, capture_output=True, text=True,
    )
    calls = Path(env["CALL_LOG"]).read_text()
    assert "data/config/study.yaml" in calls
    if worker == "collect":
        assert "data/config/approved.toml" in calls
    else:
        assert "data/selected" in calls


def test_sync_wrapper_skips_cleanly_without_run_id(tmp_path: Path) -> None:
    root, env = setup_checkout(tmp_path)
    env.pop("LACLAUGPT_RUN_ID", None)
    result = subprocess.run(
        ["bash", str(root / "scripts/run_brazil26_localhost_sync.sh")],
        cwd=tmp_path, env=env, check=True, capture_output=True, text=True,
    )
    assert "remote sync disabled" in result.stdout.lower()
    assert not Path(env["CALL_LOG"]).exists()



@pytest.mark.parametrize("worker", ["collect", "sync"])
def test_wrappers_preserve_pinned_study(tmp_path: Path, worker: str) -> None:
    root, env = setup_checkout(tmp_path)
    pinned = root / "data/config/pinned.yaml"
    pinned.write_text("study_id: pinned\n")
    env["LACLAUGPT_STUDY_CONFIG"] = str(pinned)
    with Path(env["LACLAUGPT_ENV_FILE"]).open("a") as stream:
        stream.write('LACLAUGPT_STUDY_CONFIG="missing.yaml"\n')
    subprocess.run(
        ["bash", str(root / f"scripts/run_brazil26_localhost_{worker}.sh")],
        cwd=tmp_path, env=env, check=True, capture_output=True, text=True,
    )
    assert str(pinned) in Path(env["CALL_LOG"]).read_text()


def test_cron_pins_paths_for_every_worker_and_preserves_other_jobs(tmp_path: Path) -> None:
    root, env = setup_checkout(tmp_path)
    cron = root / ".venv/bin/crontab"
    cron.write_text(
        '#!/bin/bash\nif [[ "$1" == "-l" ]]; then cat "$CRON_FILE"; '
        'else cp "$1" "$CRON_FILE"; fi\n'
    )
    cron.chmod(0o755)
    installed = tmp_path / "crontab"
    installed.write_text(
        "0 1 * * * unrelated-job\n# BEGIN LACLAUGPT BRAZIL26\n"
        "old-stale-job\n# END LACLAUGPT BRAZIL26\n"
    )
    env.update(CRON_FILE=str(installed), PATH=f"{cron.parent}:{env['PATH']}")
    for _ in range(2):
        subprocess.run(
            ["bash", str(root / "scripts/install_cron_brazil26.sh")],
            cwd=tmp_path, env=env, check=True, capture_output=True, text=True,
        )
    content = installed.read_text()
    assert "unrelated-job" in content
    assert "old-stale-job" not in content
    assert content.count("# BEGIN LACLAUGPT BRAZIL26") == 1
    jobs = [line for line in content.splitlines() if "run_brazil26" in line]
    assert len(jobs) == 3
    for job in jobs:
        tokens = shlex.split(job)
        assert f"LACLAUGPT_ENV_FILE={env['LACLAUGPT_ENV_FILE']}" in tokens
        assert "LACLAUGPT_STUDY_CONFIG=data/config/study.yaml" in tokens
        assert "LACLAUGPT_DATA_ROOT=data/selected" in tokens
    assert any(job.startswith("*/15 * * * *") for job in jobs)
