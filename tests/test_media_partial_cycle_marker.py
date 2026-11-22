"""AI26 media launchers must stay inert under the text-only policy (#450).

Legacy media-cycle marker tests assumed that the media runner MUST execute.
That is no longer correct while AI26 collects text and existing transcripts
only. Re-enabling media requires an explicit owner decision and new tests.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "launcher",
    ["run_ai26_laskin_media.sh", "run_ai26_localhost_media.sh"],
)
def test_ai26_media_launcher_is_noop_even_if_runner_would_fail(
    tmp_path: Path, launcher: str
) -> None:
    """A cron invocation must exit zero without reading config or running media."""
    root = tmp_path / "synthetic checkout"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / launcher, scripts / launcher)

    # A stub catches accidental reactivation before real binary downloads.
    bins = root / ".venv" / "bin"
    bins.mkdir(parents=True)
    call_log = tmp_path / "media_runner_called"
    stub = bins / "laclaugpt-distributed-media"
    stub.write_text(
        '#!/bin/sh\nprintf called >> "$RUNNER_CALL_LOG"\nexit 1\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)

    env = {k: v for k, v in os.environ.items() if not k.startswith("LACLAUGPT_")}
    env["RUNNER_CALL_LOG"] = str(call_log)
    env["PATH"] = str(bins) + os.pathsep + env.get("PATH", "")

    # No .env, private study config or object store exists in this checkout.
    result = subprocess.run(
        ["bash", str(scripts / launcher)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "media worker disabled by text-only collection policy" in result.stdout
    assert not call_log.exists(), "disabled media launcher invoked downloader"
