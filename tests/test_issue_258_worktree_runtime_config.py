"""Issue #258: a runtime rooted in a Git worktree must not be a dead end.

The audit found eight repetitions of

    missing Brazil26 source manifest: <checkout>/.worktrees/brazil26-runtime/data/config/brazil26.sources.toml

in ``brazil26-collect.log``. The sentence was true and the conclusion was wrong:
``data/`` is untracked, so a fresh worktree has no ``data/config/`` at all and a
runtime rooted there can *never* own the private manifest. Reporting "missing
manifest" pointed the operator at a sampling decision when the real defect was the
checkout, and offered no supported way out.

These tests build a real Git repository, a real linked worktree, and assert:

* the failure now names the linked worktree, the main checkout and the one
  supported override (``LACLAUGPT_RUNTIME_CONFIG_ROOT``);
* the override lets the worktree runtime use the main checkout's configuration,
  so it stops being a dead end;
* a genuinely absent sampling decision stays a hard stop, and no manifest, study
  config or env file is ever generated or copied -- not into the worktree, and
  not borrowed from the main checkout.

They are offline: synthetic checkouts, stubbed workers, no crontab and no live
runtime tree.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COLLECT = "run_brazil26_localhost_collect.sh"
HELPER = "scripts/runtime_config.sh"

_MANIFEST = 'enabled_platforms = ["x", "instagram", "tiktok"]\n'
_STUDY = (
    "study: brazil26\n"
    "window:\n"
    "  start: 2026-09-01\n"
    "  end: 2026-10-10\n"
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _main_checkout(tmp_path: Path, *, manifest: bool = True, config: bool = True) -> Path:
    """A main checkout whose scripts are committed and whose data/ tree is untracked."""
    main = tmp_path / "checkout"
    (main / "scripts").mkdir(parents=True)
    for name in (COLLECT, "runtime_config.sh"):
        shutil.copy(ROOT / "scripts" / name, main / "scripts" / name)
    (main / "README.md").write_text("synthetic checkout\n", encoding="utf-8")
    _git(main, "init")
    _git(main, "config", "user.name", "Synthetic Test")
    _git(main, "config", "user.email", "synthetic@example.invalid")
    _git(main, "add", ".")
    _git(main, "commit", "-m", "fixture")
    if config:
        cfg = main / "data/config"
        cfg.mkdir(parents=True)
        (cfg / "brazil26-localhost.env").write_text(
            "LACLAUGPT_PROJECT_ID=brazil26\n", encoding="utf-8"
        )
        (cfg / "brazil26.yaml").write_text(_STUDY, encoding="utf-8")
        if manifest:
            (cfg / "brazil26.sources.toml").write_text(_MANIFEST, encoding="utf-8")
    return main


def _linked_worktree(main: Path, tmp_path: Path) -> Path:
    """A fresh linked worktree: the tracked tree only, so no untracked data/."""
    worktree = tmp_path / "worktrees/brazil26-runtime"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(main, "worktree", "add", "--detach", str(worktree))
    return worktree


def _stubs(tmp_path: Path) -> Path:
    bins = tmp_path / "stubbin"
    bins.mkdir()
    for name in ("python", "laclaugpt-server-rss", "laclaugpt-collect"):
        stub = bins / name
        stub.write_text('#!/bin/bash\nprintf "%s\\n" "$@" >> "$CALL_LOG"\n', encoding="utf-8")
        stub.chmod(0o755)
    return bins


def _env(tmp_path: Path, bins: Path) -> dict[str, str]:
    """The wrapper's environment, with the operator's home neutralised.

    ``run_brazil26_localhost_collect.sh`` prepends ``$ROOT/.venv/bin`` and
    ``$HOME/.local/bin`` to PATH, so a developer who has a real
    ``laclaugpt-server-rss`` in ``~/.local/bin`` silently out-ranks this fixture's
    stub and the test measures the operator's install instead of the wrapper. The
    script is what is under test, so its PATH has to be the fixture's.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith("LACLAUGPT_")}
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env["HOME"] = str(home)
    env["PATH"] = f"{bins}:{env.get('PATH', '')}"
    env["CALL_LOG"] = str(tmp_path / "calls")
    return env


def _run(worktree: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(worktree / "scripts" / COLLECT)],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
    )


def _pin_main_configuration(env: dict[str, str], main: Path) -> None:
    """Reproduce the reported install: cron pins env/study, the manifest is not pinned."""
    env["LACLAUGPT_ENV_FILE"] = str(main / "data/config/brazil26-localhost.env")
    env["LACLAUGPT_STUDY_CONFIG"] = str(main / "data/config/brazil26.yaml")


def _calls(env: dict[str, str]) -> str:
    path = Path(env["CALL_LOG"])
    return path.read_text(encoding="utf-8") if path.exists() else ""


# --------------------------------------------------------------------------- #
# The reported dead end, and what it now says
# --------------------------------------------------------------------------- #


def test_worktree_runtime_names_the_checkout_not_a_missing_decision(tmp_path: Path) -> None:
    main = _main_checkout(tmp_path)
    worktree = _linked_worktree(main, tmp_path)
    env = _env(tmp_path, _stubs(tmp_path))
    _pin_main_configuration(env, main)
    canonical = main / "data/config/brazil26.sources.toml"
    before = canonical.read_bytes()

    result = _run(worktree, env)

    assert result.returncode == 2
    missing = worktree / "data/config/brazil26.sources.toml"
    assert f"missing Brazil26 source manifest: {missing}" in result.stderr
    # The real cause, the real root, and the supported way out.
    assert "linked Git worktree" in result.stderr
    assert str(main) in result.stderr
    assert f"LACLAUGPT_RUNTIME_CONFIG_ROOT={main}" in result.stderr
    assert f"it is there: {canonical}" in result.stderr
    # Still a hard stop, and nothing is generated, copied or run.
    assert "refusing to run" in result.stderr
    assert not missing.exists()
    assert canonical.read_bytes() == before
    assert _calls(env) == ""


def test_worktree_runtime_gate_for_the_env_file_is_diagnosed_the_same_way(tmp_path: Path) -> None:
    main = _main_checkout(tmp_path)
    worktree = _linked_worktree(main, tmp_path)
    env = _env(tmp_path, _stubs(tmp_path))

    result = _run(worktree, env)

    assert result.returncode == 2
    assert f"missing runtime env: {worktree / 'data/config/brazil26-localhost.env'}" in result.stderr
    assert "linked Git worktree" in result.stderr
    assert f"LACLAUGPT_RUNTIME_CONFIG_ROOT={main}" in result.stderr
    assert not (worktree / "data/config").exists()
    assert _calls(env) == ""


def test_configuration_root_override_makes_the_worktree_runtime_work(tmp_path: Path) -> None:
    main = _main_checkout(tmp_path)
    worktree = _linked_worktree(main, tmp_path)
    env = _env(tmp_path, _stubs(tmp_path))
    _pin_main_configuration(env, main)
    env["LACLAUGPT_RUNTIME_CONFIG_ROOT"] = str(main)

    result = _run(worktree, env)

    assert result.returncode == 0, result.stderr
    calls = _calls(env)
    assert str(main / "data/config/brazil26.sources.toml") in calls
    assert str(main / "data/config/brazil26.yaml") in calls


def test_missing_manifest_anywhere_is_still_a_hard_stop(tmp_path: Path) -> None:
    """No manifest in the main checkout either: the decision really is absent."""
    main = _main_checkout(tmp_path, manifest=False)
    worktree = _linked_worktree(main, tmp_path)
    env = _env(tmp_path, _stubs(tmp_path))
    _pin_main_configuration(env, main)

    result = _run(worktree, env)

    assert result.returncode == 2
    assert f"it is not there either: {main / 'data/config/brazil26.sources.toml'}" in result.stderr
    assert "genuinely absent" in result.stderr
    assert "never generates, copies or borrows" in result.stderr
    assert not (worktree / "data/config/brazil26.sources.toml").exists()
    assert not (main / "data/config/brazil26.sources.toml").exists()
    assert _calls(env) == ""


def test_main_checkout_missing_manifest_keeps_a_plain_message(tmp_path: Path) -> None:
    """A main checkout is *not* diagnosed as a worktree: it could hold the file."""
    main = _main_checkout(tmp_path, manifest=False)
    env = _env(tmp_path, _stubs(tmp_path))
    env["LACLAUGPT_ENV_FILE"] = str(main / "data/config/brazil26-localhost.env")
    env["LACLAUGPT_STUDY_CONFIG"] = str(main / "data/config/brazil26.yaml")

    result = _run(main, env)

    assert result.returncode == 2
    assert "missing Brazil26 source manifest" in result.stderr
    assert "linked Git worktree" not in result.stderr
    assert "LACLAUGPT_RUNTIME_CONFIG_ROOT" not in result.stderr


# --------------------------------------------------------------------------- #
# The detector itself, and the wrappers that must use it
# --------------------------------------------------------------------------- #


def test_helper_distinguishes_the_worktree_from_the_main_checkout(tmp_path: Path) -> None:
    main = _main_checkout(tmp_path)
    worktree = _linked_worktree(main, tmp_path)
    helper = ROOT / HELPER
    env = dict(os.environ, HELPER=str(helper), TARGET=str(worktree), MAIN=str(main))
    probe = 'source "$HELPER" && laclaugpt_main_checkout_root "$TARGET"'

    linked = subprocess.run(["bash", "-c", probe], env=env, capture_output=True, text=True)
    env["TARGET"] = str(main)
    plain = subprocess.run(["bash", "-c", probe], env=env, capture_output=True, text=True)

    assert linked.returncode == 0
    assert linked.stdout.strip() == str(main)
    assert plain.returncode != 0
    assert plain.stdout.strip() == ""


@pytest.mark.parametrize(
    "relative", ["scripts/run_brazil26_localhost_collect.sh", "scripts/run_ai26_localhost_collect.sh"]
)
def test_both_collect_wrappers_use_the_shared_gate(relative: str) -> None:
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert "runtime_config.sh" in text
    assert "laclaugpt_missing_runtime_config" in text
    assert "LACLAUGPT_RUNTIME_CONFIG_ROOT" in text
