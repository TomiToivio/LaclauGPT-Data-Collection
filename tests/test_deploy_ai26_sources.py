"""Synthetic tests for the explicit AI26 manifest deployment gate."""
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy_ai26_sources.py"


def invoke(tmp_path, tracked, deployed, *flags):
    target = tmp_path / "tracked.toml"
    current = tmp_path / "deployed.toml"
    target.write_text(tracked, encoding="utf-8")
    if deployed is not None:
        current.write_text(deployed, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--tracked", str(target),
         "--deployed", str(current), *flags],
        capture_output=True, text=True, check=False,
    )
    return result, current


def test_default_dry_run_does_not_mutate(tmp_path):
    old = '[[feed]]\nname="old"\nfeed_url="https://old.example/rss"\n'
    new = '[[feed]]\nname="new"\nfeed_url="https://new.example/rss"\n'
    result, current = invoke(tmp_path, new, old)
    assert result.returncode == 0
    assert "DRY RUN ONLY" in result.stdout
    assert current.read_text() == old


def test_removal_requires_explicit_acknowledgement(tmp_path):
    old = '[[feed]]\nname="old"\nfeed_url="https://old.example/rss"\n'
    new = '[[feed]]\nname="new"\nfeed_url="https://new.example/rss"\n'
    result, current = invoke(tmp_path, new, old, "--apply")
    assert result.returncode == 2
    assert current.read_text() == old
    result, current = invoke(tmp_path, new, old, "--apply", "--allow-removals")
    assert result.returncode == 0
    assert current.read_text() == new
    assert list(tmp_path.glob("deployed.toml.backup-*"))


def test_addition_apply_and_idempotence(tmp_path):
    old = '[[feed]]\nname="old"\nfeed_url="https://old.example/rss"\n'
    new = old + '[[feed]]\nname="new"\nfeed_url="https://new.example/rss"\n'
    result, current = invoke(tmp_path, new, old, "--apply")
    assert result.returncode == 0
    assert current.read_text() == new
    result, current = invoke(tmp_path, new, new, "--apply")
    assert result.returncode == 0
    assert "Already synchronized" in result.stdout
