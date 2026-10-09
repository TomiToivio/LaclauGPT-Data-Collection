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


def test_a_kind_change_is_reported_as_a_removal_and_needs_acknowledgement(tmp_path):
    """The real 2026-10-09 case: `openai_news` moved web_source -> feed.

    The identity key includes the kind, so moving a source from the blocked HTML
    page to its official RSS feed (#170) reads as one removal + one addition even
    though the source is preserved. The gate must still refuse the silent drop
    until a human acknowledges it, because the helper cannot know a removal is a
    kind change from the manifests alone.
    """
    deployed = (
        '[[web_source]]\nname = "openai_news"\nurl = "https://openai.com/news"\n'
    )
    tracked = (
        '[[feed]]\nname = "openai_news"\nfeed_url = "https://openai.com/news/rss.xml"\n'
    )
    result, current = invoke(tmp_path, tracked, deployed, "--apply")
    assert result.returncode == 2, "a kind change must not deploy silently"
    assert "removed active sources: 1" in result.stdout
    assert current.read_text() == deployed
    result, current = invoke(tmp_path, tracked, deployed, "--apply", "--allow-removals")
    assert result.returncode == 0
    assert current.read_text() == tracked


def test_symlinked_manifest_is_refused(tmp_path):
    """A symlinked runtime manifest can point anywhere; the gate must refuse it."""
    real = tmp_path / "real.toml"
    real.write_text('[[feed]]\nname="x"\nfeed_url="https://x.example/rss"\n', encoding="utf-8")
    target = tmp_path / "tracked.toml"
    target.write_text('[[feed]]\nname="y"\nfeed_url="https://y.example/rss"\n', encoding="utf-8")
    link = tmp_path / "link.toml"
    link.symlink_to(real)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--tracked", str(target), "--deployed", str(link), "--apply"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "symlink" in (result.stdout + result.stderr).lower()
