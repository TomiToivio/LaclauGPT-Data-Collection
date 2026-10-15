"""#277: the read-only runtime-freshness check reports what the repository says.

The script is exercised as a subprocess, because its exit codes are part of its
contract: 0 fresh, 1 stale, 2 could-not-check -- and the third must never be
readable as the first.

Nothing here touches the real crontab, the real runtime config, or the network.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_ai26_runtime_freshness.py"

FEED = """[[feed]]
name = "{name}"
feed_url = "https://example.invalid/{name}/feed"
priority = "P1"
{extra}
"""


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=cwd, check=False
    )


def manifest(path: Path, rows: list[tuple[str, str]]) -> None:
    body = "".join(FEED.format(name=name, extra=extra) for name, extra in rows)
    path.write_text(body, encoding="utf-8")


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def init_git(root: Path) -> None:
    """Every tree is a git checkout, like the real runtime; HEAD == origin/main."""
    git(root, "init", "-q")
    git(root, "config", "user.email", "tests@example.invalid")
    git(root, "config", "user.name", "tests")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")


def make_tree(tmp_path: Path, *, deployed_rows, tracked_rows, study_same: bool = True) -> Path:
    """A runtime tree whose configs and code checkout are both fresh by default."""
    root = tmp_path / "runtime"
    (root / "configs" / "studies").mkdir(parents=True)
    (root / "data" / "config").mkdir(parents=True)
    manifest(root / "data" / "config" / "ai26.sources.toml", deployed_rows)
    manifest(root / "configs" / "studies" / "ai26.sources.example.toml", tracked_rows)
    (root / "data" / "config" / "ai26.yaml").write_text("project: ai26\n", encoding="utf-8")
    (root / "configs" / "studies" / "ai26.example.yaml").write_text(
        "project: ai26\n" if study_same else "project: ai26\nanalysis_phase: 2\n", encoding="utf-8"
    )
    init_git(root)
    return root


# --------------------------------------------------------------------------- #
# fresh
# --------------------------------------------------------------------------- #


def test_a_fresh_runtime_exits_zero_and_says_so(tmp_path: Path) -> None:
    root = make_tree(tmp_path, deployed_rows=[("a", "")], tracked_rows=[("a", "")])
    result = run("--root", str(root))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RUNTIME FRESH" in result.stdout


def test_a_retired_row_kept_with_enabled_false_is_not_drift(tmp_path: Path) -> None:
    """Identities that no longer run are not 'missing': that is the #265 semantic."""
    root = make_tree(
        tmp_path,
        deployed_rows=[("a", "")],
        tracked_rows=[("a", ""), ("b", 'enabled = false\ninactive_reason = "retired"')],
    )
    result = run("--root", str(root))
    assert result.returncode == 0, result.stdout
    assert "RUNTIME FRESH" in result.stdout


# --------------------------------------------------------------------------- #
# stale, per check
# --------------------------------------------------------------------------- #


def test_an_audited_source_that_was_never_deployed_is_reported_stale(tmp_path: Path) -> None:
    root = make_tree(tmp_path, deployed_rows=[("a", "")], tracked_rows=[("a", ""), ("b", "")])
    result = run("--root", str(root))
    assert result.returncode == 1
    assert "STALE" in result.stdout
    assert "RUNTIME STALE" in result.stdout


def test_a_deployed_source_the_plan_no_longer_audits_is_reported_stale(tmp_path: Path) -> None:
    root = make_tree(tmp_path, deployed_rows=[("a", ""), ("c", "")], tracked_rows=[("a", "")])
    result = run("--root", str(root))
    assert result.returncode == 1


def test_a_diverged_study_config_is_reported_stale(tmp_path: Path) -> None:
    root = make_tree(tmp_path, deployed_rows=[("a", "")], tracked_rows=[("a", "")], study_same=False)
    result = run("--root", str(root))
    assert result.returncode == 1
    assert "study_config" in result.stdout


def test_a_checkout_behind_origin_main_is_reported_stale(tmp_path: Path) -> None:
    """The configs are fresh here; only the code lags -- which is exactly the #277 case."""
    root = make_tree(tmp_path, deployed_rows=[("a", "")], tracked_rows=[("a", "")])
    git(root, "commit", "-q", "--allow-empty", "-m", "merged upstream")
    git(root, "branch", "-f", "upstream", "HEAD")      # keep the newer commit reachable
    git(root, "reset", "-q", "--hard", "HEAD~1")       # this checkout is older again
    git(root, "update-ref", "refs/remotes/origin/main", "upstream")
    result = run("--root", str(root))
    assert result.returncode == 1
    assert "behind origin/main" in result.stdout
    assert "RUNTIME STALE" in result.stdout


def test_a_checkout_ahead_of_origin_main_is_not_called_fresh(tmp_path: Path) -> None:
    root = make_tree(tmp_path, deployed_rows=[("a", "")], tracked_rows=[("a", "")])
    git(root, "commit", "-q", "--allow-empty", "-m", "local work")
    result = run("--root", str(root))
    assert "AHEAD" in result.stdout
    assert result.returncode == 1


def test_uncommitted_changes_are_reported_even_when_the_refs_match(tmp_path: Path) -> None:
    root = make_tree(tmp_path, deployed_rows=[("a", "")], tracked_rows=[("a", "")])
    (root / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")
    result = run("--root", str(root))
    assert "uncommitted changes" in result.stdout


# --------------------------------------------------------------------------- #
# cannot check -- must never read as an all-clear
# --------------------------------------------------------------------------- #


def test_a_missing_deployed_file_cannot_check_and_never_reads_as_fresh(tmp_path: Path) -> None:
    root = make_tree(tmp_path, deployed_rows=[("a", "")], tracked_rows=[("a", "")])
    (root / "data" / "config" / "ai26.sources.toml").unlink()
    result = run("--root", str(root))
    assert result.returncode == 2
    assert "RUNTIME UNKNOWN" in result.stdout
    assert "RUNTIME FRESH" not in result.stdout
    assert "NOT an all-clear" in result.stdout


def test_a_checkout_without_an_origin_main_ref_cannot_check(tmp_path: Path) -> None:
    root = make_tree(tmp_path, deployed_rows=[("a", "")], tracked_rows=[("a", "")])
    git(root, "update-ref", "-d", "refs/remotes/origin/main")
    result = run("--root", str(root))
    assert result.returncode == 2
    assert "RUNTIME UNKNOWN" in result.stdout


# --------------------------------------------------------------------------- #
# machine-readable mode
# --------------------------------------------------------------------------- #


def test_json_mode_reports_each_check_and_the_overall_verdict(tmp_path: Path) -> None:
    root = make_tree(tmp_path, deployed_rows=[("a", "")], tracked_rows=[("a", ""), ("b", "")])
    result = run("--root", str(root), "--json")
    payload = json.loads(result.stdout)
    assert payload["fresh"] is False
    assert payload["stale_count"] >= 1
    names = {c["check"] for c in payload["checks"]}
    assert names == {"source_manifest", "study_config", "code"}
    assert payload["checks"][0]["added"], "the added identity must be named"


def test_quiet_mode_prints_only_the_verdict(tmp_path: Path) -> None:
    root = make_tree(tmp_path, deployed_rows=[("a", "")], tracked_rows=[("a", "")])
    result = run("--root", str(root), "--quiet")
    assert result.stdout.strip().startswith("RUNTIME FRESH")
    assert "\n" not in result.stdout.strip()
