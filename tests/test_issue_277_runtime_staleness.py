"""Issue #277: the read-only runtime staleness check.

The point of the check is that it *detects* rather than repairs, so these tests pin both
halves: it finds every kind of drift, and it changes nothing while finding them.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_ai26_runtime.py"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False, cwd=cwd,
    )


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """A repository root whose configs mirror the real tracked/deployed layout."""
    (tmp_path / "configs" / "studies").mkdir(parents=True)
    (tmp_path / "data" / "config").mkdir(parents=True)
    return tmp_path


def make_repo(path: Path, *, extra_commits: int = 0) -> Path:
    """A real checkout whose origin/main sits `extra_commits` ahead of HEAD.

    That is the deployed shape: the reviewed release is merged, the host still runs an
    older commit. HEAD *ahead* of origin/main is the operator's own local work instead.
    """
    path.mkdir(parents=True, exist_ok=True)
    git("init", "--quiet", "--initial-branch=main", cwd=path)
    git("config", "user.email", "test@example.invalid", cwd=path)
    git("config", "user.name", "test", cwd=path)
    (path / "file.txt").write_text("first\n", encoding="utf-8")
    git("add", ".", cwd=path)
    git("commit", "--quiet", "-m", "first", cwd=path)
    for step in range(extra_commits):
        (path / "file.txt").write_text(f"release step {step}\n", encoding="utf-8")
        git("commit", "--quiet", "-am", f"release {step}", cwd=path)
    git("update-ref", "refs/remotes/origin/main", "HEAD", cwd=path)
    if extra_commits:
        git("reset", "--quiet", "--hard", f"HEAD~{extra_commits}", cwd=path)
    return path


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A clean checkout sitting exactly on the reviewed revision."""
    return make_repo(tmp_path / "LaclauGPT-Data-Collection")


@pytest.fixture()
def checkout(tmp_path: Path) -> Path:
    """A clean checkout two commits behind the reviewed revision."""
    return make_repo(tmp_path / "LaclauGPT-Data-Analysis", extra_commits=2)


# ------------------------------------------------------------------ the config copies

def test_matching_config_is_in_sync(root: Path, repo: Path) -> None:
    content = b"[[feed]]\nurl = 'https://example.invalid/feed'\n"
    (root / "configs/studies/ai26.sources.example.toml").write_bytes(content)
    (root / "data/config/ai26.sources.toml").write_bytes(content)
    (root / "configs/studies/ai26.example.yaml").write_bytes(b"paper: local.yaml\n")
    (root / "data/config/ai26.yaml").write_bytes(b"paper: local.yaml\n")

    result = run("--root", str(root), "--checkout", str(repo))

    assert result.returncode == 0, result.stdout
    assert "runtime result: in sync" in result.stdout


def test_drifted_config_is_stale_and_names_both_digests(root: Path, repo: Path) -> None:
    (root / "configs/studies/ai26.sources.example.toml").write_bytes(b"active = true\n")
    (root / "data/config/ai26.sources.toml").write_bytes(b"active = false\n")

    result = run("--root", str(root), "--checkout", str(repo))

    assert result.returncode == 1
    assert "ai26.sources.toml" in result.stdout
    assert "drift: tracked" in result.stdout and "!= deployed" in result.stdout


def test_undeployed_config_is_stale_rather_than_an_error(root: Path, repo: Path) -> None:
    (root / "configs/studies/ai26.example.yaml").write_bytes(b"paper: local.yaml\n")

    result = run("--root", str(root), "--checkout", str(repo))

    assert result.returncode == 1
    assert "not deployed" in result.stdout


def test_missing_tracked_config_is_reported(root: Path, repo: Path) -> None:
    result = run("--root", str(root), "--checkout", str(repo))

    assert result.returncode == 1
    assert "tracked file is missing" in result.stdout


# -------------------------------------------------------------------- the code copies

def test_checkout_behind_origin_main_reports_the_exact_lag(root: Path, checkout: Path) -> None:
    result = run("--root", str(root), "--checkout", str(checkout))

    assert result.returncode == 1
    assert "2 commit(s) behind origin/main" in result.stdout


def test_clean_checkout_at_origin_main_is_in_sync(root: Path, checkout: Path) -> None:
    (root / "configs/studies/ai26.sources.example.toml").write_bytes(b"x = 1\n")
    (root / "data/config/ai26.sources.toml").write_bytes(b"x = 1\n")
    (root / "configs/studies/ai26.example.yaml").write_bytes(b"y = 1\n")
    (root / "data/config/ai26.yaml").write_bytes(b"y = 1\n")
    git("merge", "--ff-only", "refs/remotes/origin/main", cwd=checkout)

    result = run("--root", str(root), "--checkout", str(checkout))

    assert result.returncode == 0, result.stdout
    assert "runtime result: in sync" in result.stdout


def test_uncommitted_operator_changes_are_visible_and_do_not_hide_the_lag(
    root: Path, checkout: Path
) -> None:
    (checkout / "local-operator-note.txt").write_text("hand edit\n", encoding="utf-8")

    result = run("--root", str(root), "--checkout", str(checkout))

    assert result.returncode == 1
    assert "uncommitted path(s)" in result.stdout
    assert "behind origin/main" in result.stdout


def test_non_checkout_is_reported_not_crashed(root: Path, tmp_path: Path) -> None:
    result = run("--root", str(root), "--checkout", str(tmp_path / "elsewhere"))

    assert result.returncode == 1
    assert "not a Git checkout" in result.stdout


def test_several_checkouts_can_be_checked_in_one_call(root: Path, repo: Path, checkout: Path) -> None:
    result = run("--root", str(root), "--checkout", str(checkout), "--checkout", str(repo))

    assert result.returncode == 1
    assert f"code ({checkout.name})" in result.stdout
    assert f"code ({repo.name})" in result.stdout


# ------------------------------------------------------------------------- the gate

def test_json_output_is_machine_readable(root: Path, repo: Path) -> None:
    result = run("--root", str(root), "--json")

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["stale"] is True
    assert {finding["name"] for finding in payload["findings"]} >= {"ai26.sources.toml", "ai26.yaml"}


def test_a_sibling_checkout_without_the_package_is_not_called_stale(
    root: Path, repo: Path, tmp_path: Path
) -> None:
    """A checkout that does not own the package must not be probed into a false STALE."""
    sibling = make_repo(tmp_path / "LaclauGPT-Data-Analysis", extra_commits=0)
    (sibling / ".venv" / "bin").mkdir(parents=True)
    (sibling / ".venv" / "bin" / "python").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    for name, content in (
        ("configs/studies/ai26.sources.example.toml", b"x = 1\n"),
        ("data/config/ai26.sources.toml", b"x = 1\n"),
        ("configs/studies/ai26.example.yaml", b"y = 1\n"),
        ("data/config/ai26.yaml", b"y = 1\n"),
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    result = run("--root", str(root), "--checkout", str(repo), "--checkout", str(sibling))

    assert result.returncode == 0, result.stdout
    assert "is not part of this checkout; skipped" in result.stdout


def test_the_collect_wrapper_reports_drift_without_applying_it() -> None:
    """The hourly stage may report a stale runtime; it must never enforce or fetch one."""
    wrapper = (ROOT / "scripts" / "run_ai26_laskin_collect.sh").read_text(encoding="utf-8")

    assert "check_ai26_runtime.py" in wrapper
    assert "if ! \"${RUNTIME_CHECK[@]}\"" in wrapper, "the check must be guarded, or set -e aborts the cycle"
    assert "--fetch" not in wrapper, "cron must not depend on the network"
    assert "--apply" not in wrapper


def test_the_check_writes_nothing(root: Path, checkout: Path) -> None:
    """Read-only is the whole contract: not one byte and not one new path."""
    (root / "configs/studies/ai26.sources.example.toml").write_bytes(b"x = 1\n")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    before_checkout = sorted(item.name for item in checkout.iterdir())

    run("--root", str(root), "--checkout", str(checkout))

    after = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert after == before
    assert sorted(item.name for item in checkout.iterdir()) == before_checkout
