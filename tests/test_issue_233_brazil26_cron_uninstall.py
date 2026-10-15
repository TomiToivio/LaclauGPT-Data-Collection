"""Issue #233 acceptance coverage: the cron installer's removal/status modes.

These tests are offline by design and never go near a real crontab: every case
drives a synthetic ``crontab`` shim on ``PATH`` whose store is a file under
``tmp_path``. The audit's G2 gap was that the documented operation cycle
("install, start, health check, log inspection, stopping/removing cron, and
manual one-shot download") had no way to *remove* the schedule, and that
``scripts/install_cron_brazil26.sh`` grew no uninstall mode at all.

What is asserted here is the safety contract of that removal: the dry run
changes nothing, the real removal strips only the entries this installer owns
and leaves a decoy crontab line intact, a second removal is a no-op, the
previous crontab is backed up, and the command refuses with a non-zero exit
when it cannot be sure which entries are its own. No crontab is installed,
enabled, removed or activated by the tests themselves.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# A crontab that belongs to somebody else. The third line even names "brazil":
# ownership must be decided by the wrapper names this installer writes, never by
# a keyword, or an uninstall could delete an unrelated job.
_DECOYS = (
    "# a hand-written job that is not ours\n"
    "0 3 * * * /usr/local/bin/borgbackup.sh --daily\n"
    "@daily /home/tomi/bin/brazil-notes.sh\n"
)

_OWNED_WRAPPERS = (
    "run_brazil26_localhost_sync.sh",
    "run_brazil26_localhost_collect.sh",
    "run_brazil26_localhost_media.sh",
    "run_brazil26_localhost_media_distributed.sh",
)

_BEGIN = "# BEGIN LACLAUGPT BRAZIL26"
_END = "# END LACLAUGPT BRAZIL26"


@dataclass
class Harness:
    """A synthetic checkout plus a ``crontab`` shim, so nothing touches cron."""

    root: Path
    script: Path
    store: Path
    shim: Path
    backup_dir: Path
    env: dict[str, str]

    def run(self, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        env.update(env_extra or {})
        return subprocess.run(
            ["bash", str(self.script), *args],
            cwd=str(self.root),
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
            # Never inherit the developer's terminal: a stray tty would make the
            # unprompted uninstall block on a confirmation prompt.
            stdin=subprocess.DEVNULL,
        )

    def crontab(self) -> str:
        return self.store.read_text(encoding="utf-8")

    def install(self, env_extra: dict[str, str] | None = None) -> None:
        result = self.run("install", env_extra=env_extra)
        assert result.returncode == 0, result.stderr


def _crontab_shim(tmp_path: Path, store: Path, *, unreadable: bool = False) -> Path:
    shim = tmp_path / "bin"
    shim.mkdir(parents=True, exist_ok=True)
    crontab = shim / "crontab"
    if unreadable:
        crontab.write_text(
            "#!/usr/bin/env bash\n"
            'echo "crontab: cannot open crontab: Permission denied" >&2\n'
            "exit 1\n",
            encoding="utf-8",
        )
    else:
        crontab.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"STORE={shlex.quote(str(store))}\n"
            'if [[ $# -eq 1 && "$1" == "-l" ]]; then cat "$STORE" 2>/dev/null || true; exit 0; fi\n'
            'if [[ $# -ne 1 ]]; then echo "crontab: unexpected arguments" >&2; exit 2; fi\n'
            'cp "$1" "$STORE"\n',
            encoding="utf-8",
        )
    crontab.chmod(0o755)
    return shim


def _harness(tmp_path: Path, *, initial: str = _DECOYS, unreadable: bool = False) -> Harness:
    """A synthetic checkout running a *copy* of the real installer.

    The copy is what makes ``ROOT`` (and therefore the backup directory and log
    directory) resolve inside ``tmp_path`` instead of the repository checkout.
    """
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "data/config").mkdir(parents=True)
    (root / "data/logs").mkdir(parents=True)
    script = root / "scripts/install_cron_brazil26.sh"
    shutil.copy2(ROOT / "scripts/install_cron_brazil26.sh", script)
    env_file = root / "data/config/brazil26-localhost.env"
    env_file.write_text("LACLAUGPT_PROJECT_ID=brazil26\n", encoding="utf-8")
    study = tmp_path / "study.yaml"
    study.write_text("study: brazil26\n", encoding="utf-8")
    store = tmp_path / "crontab.txt"
    store.write_text(initial, encoding="utf-8")
    shim = _crontab_shim(tmp_path, store, unreadable=unreadable)
    backup_dir = tmp_path / "backups"
    env = {
        "PATH": f"{shim}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "LACLAUGPT_ENV_FILE": str(env_file),
        "LACLAUGPT_STUDY_CONFIG": str(study),
        "LACLAUGPT_DATA_ROOT": str(root / "data"),
        "LACLAUGPT_CRON_BACKUP_DIR": str(backup_dir),
    }
    return Harness(root=root, script=script, store=store, shim=shim, backup_dir=backup_dir, env=env)


def _backups(h: Harness) -> list[Path]:
    return sorted(h.backup_dir.glob("crontab-brazil26-*.txt"))


# --------------------------------------------------------------------------- #
# Install: the dry run writes nothing
# --------------------------------------------------------------------------- #

def test_install_dry_run_prints_the_block_and_writes_nothing(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    before = h.crontab()

    result = h.run("install", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert h.crontab() == before, "the install dry run modified the crontab"
    assert _BEGIN in result.stdout and _END in result.stdout
    assert "the crontab was NOT modified" in result.stdout


# --------------------------------------------------------------------------- #
# Uninstall: dry run removes nothing
# --------------------------------------------------------------------------- #

def test_removal_dry_run_prints_the_plan_and_removes_nothing(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    h.install()
    installed = h.crontab()

    result = h.run("uninstall", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert h.crontab() == installed, "the removal dry run modified the crontab"
    # The plan names exactly what would go, and counts what would not.
    for name in ("brazil26-sync.log", "brazil26-collect.log", "brazil26-media.log"):
        assert name in result.stdout
    assert "other crontab entries left untouched: 3" in result.stdout
    assert "nothing was removed" in result.stdout
    assert _backups(h) == [], "the dry run wrote a backup as if it had removed something"


# --------------------------------------------------------------------------- #
# Uninstall: only the owned entries go, a decoy stays
# --------------------------------------------------------------------------- #

def test_removal_strips_only_the_owned_entries_and_keeps_the_decoy(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    h.install()
    assert _BEGIN in h.crontab()

    result = h.run("uninstall", "--yes")

    assert result.returncode == 0, result.stderr
    after = h.crontab()
    assert _BEGIN not in after and _END not in after
    for wrapper in _OWNED_WRAPPERS:
        assert wrapper not in after, f"{wrapper} survived the removal"
    # The unrelated entries are preserved byte-for-byte, including the one that
    # merely contains the word "brazil".
    assert after == _DECOYS
    assert "/usr/local/bin/borgbackup.sh" in after
    assert "brazil-notes.sh" in after


def test_removal_also_takes_an_unmanaged_brazil26_entry(tmp_path: Path) -> None:
    """Ownership is by wrapper name, not by the marker block alone.

    An earlier version of the installer, or a hand edit, can leave a media entry
    *outside* the block; leaving it behind would keep a 15-minute Allas worker
    scheduled after the "removal" reported success.
    """
    h = _harness(tmp_path)
    h.install()
    stale = (
        "*/15 * * * * cd /workspace && /bin/bash scripts/"
        "run_brazil26_localhost_media_distributed.sh >> data/logs/brazil26-media.log 2>&1\n"
    )
    h.store.write_text(h.crontab() + stale, encoding="utf-8")

    result = h.run("uninstall", "--yes")

    assert result.returncode == 0, result.stderr
    assert h.crontab() == _DECOYS


@pytest.mark.parametrize("mode", ["uninstall", "remove", "--uninstall", "--remove"])
def test_both_removal_spellings_work(tmp_path: Path, mode: str) -> None:
    h = _harness(tmp_path)
    h.install()

    result = h.run(mode, "--yes")

    assert result.returncode == 0, result.stderr
    assert h.crontab() == _DECOYS


def test_removal_backs_up_the_previous_crontab(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    h.install()
    installed = h.crontab()

    result = h.run("uninstall", "--yes")

    assert result.returncode == 0, result.stderr
    backups = _backups(h)
    assert len(backups) == 1, backups
    assert backups[0].read_text(encoding="utf-8") == installed
    assert str(backups[0]) in result.stdout


# --------------------------------------------------------------------------- #
# Uninstall: idempotency
# --------------------------------------------------------------------------- #

def test_removal_is_idempotent(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    h.install()

    first = h.run("uninstall", "--yes")
    assert first.returncode == 0, first.stderr
    after_first = h.crontab()

    second = h.run("uninstall", "--yes")

    assert second.returncode == 0, second.stderr
    assert h.crontab() == after_first, "the second removal changed the crontab"
    assert "nothing to remove" in second.stdout
    assert len(_backups(h)) == 1, "the no-op second run still wrote a backup"


def test_removal_of_an_absent_block_is_a_successful_no_op(tmp_path: Path) -> None:
    """A fresh workstation with no Brazil26 block must not look like a failure."""
    h = _harness(tmp_path)

    result = h.run("uninstall", "--yes")

    assert result.returncode == 0, result.stderr
    assert h.crontab() == _DECOYS
    assert _backups(h) == []


# --------------------------------------------------------------------------- #
# Uninstall: the refusal paths
# --------------------------------------------------------------------------- #

def test_removal_without_confirmation_refuses_and_writes_nothing(tmp_path: Path) -> None:
    """An unattended run must never strip a schedule by accident."""
    h = _harness(tmp_path)
    h.install()
    installed = h.crontab()

    result = h.run("uninstall")

    assert result.returncode == 2
    assert h.crontab() == installed
    assert "--yes" in result.stderr
    assert _backups(h) == []


@pytest.mark.parametrize(
    "broken",
    [
        f"{_BEGIN}\n12 * * * * /bin/bash scripts/run_brazil26_localhost_sync.sh\n",
        f"0 3 * * * /usr/local/bin/borgbackup.sh --daily\n{_END}\n",
        f"{_BEGIN}\n12 * * * * echo one\n{_END}\n{_BEGIN}\n22 * * * * echo two\n",
    ],
)
def test_removal_refuses_an_unbalanced_marker_block(tmp_path: Path, broken: str) -> None:
    """Unbalanced markers are the case where "mine" cannot be told from "yours"."""
    h = _harness(tmp_path, initial=broken)

    result = h.run("uninstall", "--yes")

    assert result.returncode == 2
    assert h.crontab() == broken, "the refusal still modified the crontab"
    assert "refusing to change the crontab" in result.stderr
    assert _backups(h) == []


def test_removal_refuses_an_unreadable_crontab(tmp_path: Path) -> None:
    h = _harness(tmp_path, unreadable=True)

    result = h.run("uninstall", "--yes")

    assert result.returncode == 2
    assert "cannot read the crontab" in result.stderr
    assert h.crontab() == _DECOYS, "the removal wrote a crontab it could not read"
    assert _backups(h) == []


# --------------------------------------------------------------------------- #
# Status: the health check for the installed schedule
# --------------------------------------------------------------------------- #

def test_status_reports_absent_then_healthy(tmp_path: Path) -> None:
    h = _harness(tmp_path)

    absent = h.run("status")
    assert absent.returncode == 3
    assert "installed: no" in absent.stdout
    assert "health: absent" in absent.stdout

    h.install()
    healthy = h.run("status")

    assert healthy.returncode == 0, healthy.stderr
    assert "installed: yes" in healthy.stdout
    assert "media_mode: local" in healthy.stdout
    assert "media_cadence: 30-minute" in healthy.stdout
    assert "workers: sync=1 collect=1" in healthy.stdout
    assert "health: ok" in healthy.stdout


def test_status_reports_the_allas_media_mode(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    h.install(env_extra={"LACLAUGPT_BRAZIL26_MEDIA_MODE": "allas"})

    result = h.run("status")

    assert result.returncode == 0, result.stderr
    assert "media_mode: allas" in result.stdout
    assert "run_brazil26_localhost_media_distributed.sh" in h.crontab()


def test_status_flags_a_stale_fifteen_minute_entry(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    h.install()
    h.store.write_text(
        h.crontab()
        + "*/15 * * * * cd /workspace && /bin/bash scripts/run_brazil26_localhost_media.sh\n",
        encoding="utf-8",
    )

    result = h.run("status")

    assert result.returncode == 3
    assert "media_cadence: stale 15-minute entry present" in result.stdout
    assert "health: degraded" in result.stdout


def test_status_names_the_logs_for_inspection(tmp_path: Path) -> None:
    """The "log inspection" half of the operation cycle, without a second tool."""
    h = _harness(tmp_path)
    (h.root / "data/logs/brazil26-media.log").write_text("x\n", encoding="utf-8")
    h.install()

    result = h.run("status")

    assert result.returncode == 0, result.stderr
    for name in ("brazil26-sync.log", "brazil26-collect.log", "brazil26-media.log"):
        assert name in result.stdout
    assert "(absent)" in result.stdout
    assert "brazil26-media.log (2 bytes)" in result.stdout
    assert "tail -n 50" in result.stdout


def test_status_is_read_only(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    h.install()
    installed = h.crontab()

    for _ in range(2):
        assert h.run("status").returncode == 0

    assert h.crontab() == installed
    assert _backups(h) == []


# --------------------------------------------------------------------------- #
# CLI surface
# --------------------------------------------------------------------------- #

def test_help_is_offered_and_an_unknown_argument_is_rejected(tmp_path: Path) -> None:
    h = _harness(tmp_path)

    helped = h.run("--help")
    assert helped.returncode == 0
    assert "uninstall" in helped.stdout

    unknown = h.run("--definitely-not-a-mode")
    assert unknown.returncode == 2
    assert "unknown argument" in unknown.stderr
