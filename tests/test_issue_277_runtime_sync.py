"""Read-only staleness gate tests using an isolated temporary git checkout."""
import importlib.util
import subprocess
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts/check_ai26_runtime_sync.py"
spec = importlib.util.spec_from_file_location("ai26_sync_gate", MODULE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def command(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def setup(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    command(root, "init")
    command(root, "config", "user.name", "Synthetic Test")
    command(root, "config", "user.email", "synthetic@example.invalid")
    pairs = [
        ("configs/studies/ai26.sources.example.toml", "data/config/ai26.sources.toml"),
        ("configs/studies/ai26.example.yaml", "data/config/ai26.yaml"),
    ]
    for tracked, deployed in pairs:
        for name in (tracked, deployed):
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("synthetic fixture", encoding="utf-8")
    command(root, "add", ".")
    command(root, "commit", "-m", "fixture")
    head = gate.git(root, "rev-parse", "HEAD")
    command(root, "update-ref", "refs/remotes/origin/main", head)
    return root


def test_in_sync(tmp_path):
    root = setup(tmp_path)
    ok, line = gate.evaluate(root)
    assert ok
    assert "AI26_RUNTIME_SYNC=in_sync" in line
    assert "tree=clean" in line


def test_config_drift_detected_without_mutation(tmp_path):
    root = setup(tmp_path)
    target = root / "data/config/ai26.sources.toml"
    target.write_text("changed runtime", encoding="utf-8")
    ok, line = gate.evaluate(root)
    assert not ok
    assert "sources=stale" in line
    assert target.read_text() == "changed runtime"


def test_code_behind_detected(tmp_path):
    root = setup(tmp_path)
    initial = gate.git(root, "rev-parse", "HEAD")
    (root / "new.txt").write_text("new", encoding="utf-8")
    command(root, "add", "new.txt")
    command(root, "commit", "-m", "next")
    updated = gate.git(root, "rev-parse", "HEAD")
    command(root, "update-ref", "refs/remotes/origin/main", updated)
    command(root, "reset", "--hard", initial)
    ok, line = gate.evaluate(root)
    assert not ok
    assert "code=stale" in line and "behind=1" in line


def test_missing_ref_fails_closed(tmp_path):
    root = setup(tmp_path)
    ok, line = gate.evaluate(root, remote="origin/nonexistent")
    assert not ok
    assert "code=unknown" in line
