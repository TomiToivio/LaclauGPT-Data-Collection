# -*- coding: utf-8 -*-
"""Issue #240: the collect end marker must be emitted on EVERY exit path.

`#217` fixed one path: the runner exits 1 for a partial tick, and the wrapper no
longer aborts under `set -e` before the marker. But on 2026-10-09T03:10 a tick
emitted its **complete, parseable JSON record** and then no end marker at all —
with no OOM, no reboot, and no cron timeout to explain it (whole-log history:
540 starts / 523 ends). The cause was not identifiable from the evidence, so the
fix makes the invariant structural instead of guessing the trigger.

What these tests pin:

1. The EXIT trap fires on the **normal** paths (clean and partial) — the #217
   behaviour must not regress.
2. It fires when the wrapper is **signalled while the runner is still working** —
   the #240 case, which previously lost the marker entirely.
3. The marker is emitted **exactly once**, so a trap does not double-log.
4. A signal **during preflight/lock exit** does NOT emit an end for a tick that
   never started (the trap is armed only after the start marker).
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "run_ai26_laskin_collect.sh"


def _setup(tmp_path: Path, runner_body: str) -> tuple[Path, dict[str, str]]:
    """A synthetic checkout holding the real wrapper and a stub runner."""
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(WRAPPER, root / "scripts" / "run_ai26_laskin_collect.sh")

    bins = root / ".venv" / "bin"
    bins.mkdir(parents=True)
    stub = bins / "python"
    stub.write_text("#!/bin/bash\n" + runner_body, encoding="utf-8")
    stub.chmod(0o755)

    cfg = root / "data" / "config"
    cfg.mkdir(parents=True)
    (cfg / "ai26.yaml").write_text("study: ai26\n", encoding="utf-8")
    (cfg / "ai26.sources.toml").write_text("# synthetic\n", encoding="utf-8")
    env_file = tmp_path / "synthetic.env"
    env_file.write_text("", encoding="utf-8")

    env = {k: v for k, v in os.environ.items() if not k.startswith("LACLAUGPT_")}
    env.update(
        LACLAUGPT_ENV_FILE=str(env_file),
        LACLAUGPT_AI26_STUDY_CONFIG=str(cfg / "ai26.yaml"),
        LACLAUGPT_AI26_SOURCE_MANIFEST=str(cfg / "ai26.sources.toml"),
        LACLAUGPT_AI26_COLLECT_LOCK=str(root / "data" / "tmp" / "collect.lock"),
    )
    return root, env


def _run(tmp_path: Path, runner_body: str) -> subprocess.CompletedProcess[str]:
    root, env = _setup(tmp_path, runner_body)
    return subprocess.run(
        ["bash", str(root / "scripts" / "run_ai26_laskin_collect.sh")],
        cwd=tmp_path, env=env, text=True, capture_output=True, check=False,
    )


def _count_ends(stdout: str) -> int:
    return sum(1 for line in stdout.splitlines() if "collection end" in line)


# --------------------------------------------------------- the #217 behaviour --

def test_a_partial_tick_still_emits_its_marker(tmp_path: Path) -> None:
    """The #217 behaviour must not regress: runner exit 1 still logs the marker."""
    result = _run(tmp_path, 'exit 1\n')
    assert "AI26 Laskin collection start" in result.stdout
    assert _count_ends(result.stdout) == 1
    assert "runner_status=1" in result.stdout
    assert result.returncode == 1


def test_a_clean_tick_emits_a_plain_marker(tmp_path: Path) -> None:
    result = _run(tmp_path, 'exit 0\n')
    assert _count_ends(result.stdout) == 1
    assert "runner_status" not in result.stdout
    assert result.returncode == 0


def test_the_marker_is_emitted_exactly_once(tmp_path: Path) -> None:
    """A trap must not double-log: exactly one end marker per tick, either path."""
    for index, body in enumerate(('exit 0\n', 'exit 1\n', 'exit 3\n')):
        result = _run(tmp_path / f"case{index}", body)
        assert _count_ends(result.stdout) == 1, f"body={body!r} logged {result.stdout!r}"


# ------------------------------------------------------------ the #240 case --

def test_a_signalled_tick_still_emits_an_end_marker(tmp_path: Path) -> None:
    """The #240 case: TERM while the runner is still working.

    Before the fix this lost the marker entirely, leaving a start with no end.
    """
    root, env = _setup(tmp_path, "sleep 30\n")
    # Capture to a FILE rather than a pipe: the signalled tick's own child may hold
    # the pipe open for a moment, and `communicate()` on a pipe then blocks past the
    # assertion we are trying to make. A file removes that coupling entirely.
    log = tmp_path / "tick.log"
    with log.open("w") as handle:
        proc = subprocess.Popen(
            ["bash", str(root / "scripts" / "run_ai26_laskin_collect.sh")],
            cwd=tmp_path, env=env, text=True, stdout=handle, stderr=subprocess.STDOUT,
        )
        # Wait for the start marker, so the TERM lands after the trap is armed and
        # while the runner is still working.
        deadline = time.time() + 10
        while time.time() < deadline:
            if "collection start" in log.read_text(encoding="utf-8"):
                break
            time.sleep(0.05)
        else:  # pragma: no cover - the wrapper never started
            proc.kill()
            raise AssertionError("the wrapper never emitted its start marker")

        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
            raise AssertionError("the wrapper did not exit after SIGTERM")

    out = log.read_text(encoding="utf-8")

    assert "AI26 Laskin collection start" in out
    assert _count_ends(out) == 1, f"a signalled tick lost its end marker: {out!r}"
    assert "interrupted" in out, "the marker does not name the signal"
    assert proc.returncode != 0, "an interrupted tick must not report success"


def test_the_trap_is_armed_after_the_start_marker_only(tmp_path: Path) -> None:
    """A preflight/lock exit must not emit an end for a tick that never started."""
    root, env = _setup(tmp_path, "exit 0\n")
    # Make the lock file unopenable so the wrapper exits early, before `start`.
    (root / "data" / "tmp").mkdir(parents=True, exist_ok=True)
    lock = root / "data" / "tmp" / "collect.lock"
    lock.mkdir()  # a DIRECTORY where a file is expected: `exec 9>` fails
    result = subprocess.run(
        ["bash", str(root / "scripts" / "run_ai26_laskin_collect.sh")],
        cwd=tmp_path, env=env, text=True, capture_output=True, check=False,
    )
    assert "AI26 Laskin collection start" not in result.stdout
    assert _count_ends(result.stdout) == 0, "an unstarted tick must not log an end"


def test_the_wrapper_arms_an_exit_trap() -> None:
    """Pin the mechanism, so a later edit cannot quietly go back to the old shape."""
    text = WRAPPER.read_text(encoding="utf-8")
    assert "EMIT_END_MARKER" in text or "emit_end_marker" in text
    assert "END_EMITTED" in text, "the exactly-once guard is missing"
    # The trap must be armed after the start marker. Use the LAST definition+arming
    # site (rindex), not the first: a mutation that inserts an earlier arm is exactly
    # what this guards against, and index() would find the wrong one.
    arm_at = text.rindex("trap 'emit_end_marker' EXIT")
    start_at = text.index("AI26 Laskin collection start")
    assert start_at < arm_at, "the trap is armed before the start marker"
    # and the trap must be armed only once — the exactly-once guarantee depends on
    # there being a single arming site
    assert text.count("trap 'emit_end_marker' EXIT") == 1, "the EXIT trap is armed more than once"


def test_a_killed_runner_does_not_leave_the_child_running(tmp_path: Path) -> None:
    """The signal handler must stop the runner, not orphan it.

    A handler that exits without killing the child leaves a runner writing into a
    log for a tick that is already over — and, if it holds the lock, blocks the next
    tick. Assert the child is gone shortly after the wrapper exits.
    """
    root, env = _setup(tmp_path, 'echo "$$" > "$CHILD_PID_FILE"\nsleep 30\n')
    pid_file = tmp_path / "child.pid"
    env["CHILD_PID_FILE"] = str(pid_file)
    log = tmp_path / "tick.log"
    with log.open("w") as handle:
        proc = subprocess.Popen(
            ["bash", str(root / "scripts" / "run_ai26_laskin_collect.sh")],
            cwd=tmp_path, env=env, text=True, stdout=handle, stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 10
        while time.time() < deadline and not pid_file.exists():
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=15)

    child_pid = int(pid_file.read_text().strip())
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return  # the child is gone: correct
        time.sleep(0.05)
    os.kill(child_pid, signal.SIGKILL)
    raise AssertionError("the wrapper exited but left the runner running (orphan)")
