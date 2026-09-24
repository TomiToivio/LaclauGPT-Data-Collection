"""Regression coverage for the Brazil26 Firefox executable contract (#174).

Two defects were found while running the localhost profile on WSL:

1. ``LACLAUGPT_FIREFOX_COMMAND`` could not express a Windows Firefox path.
   ``_read_env_file`` strips surrounding quotes, so the value reaches
   ``shlex.split`` unquoted and a spaced path was shredded into bogus tokens.
2. Preflight reported ``status: ok`` for an executable that cannot run.
   ``shutil.which("firefox")`` returns Ubuntu's ``/usr/bin/firefox`` shim, which
   exits 1 unless the firefox snap is installed, so the researcher session would
   have been launched at a dead executable.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from laclaugpt_data_collection import brazil26_browser


def test_firefox_command_keeps_spaced_executable_path_intact(tmp_path: Path) -> None:
    # A real path containing spaces, standing in for
    # "<mount>/Program Files/Mozilla Firefox/firefox.exe" on WSL.
    spaced_dir = tmp_path / "Program Files" / "Mozilla Firefox"
    spaced_dir.mkdir(parents=True)
    executable = spaced_dir / "firefox.exe"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")

    command = brazil26_browser._firefox_command(
        {"LACLAUGPT_FIREFOX_COMMAND": str(executable)}
    )
    assert command == [str(executable)]


def test_firefox_command_still_splits_multi_word_command_lines(tmp_path: Path) -> None:
    # A genuine command line must keep shell-style splitting; only a value that
    # names an existing path is treated as one executable.
    command = brazil26_browser._firefox_command(
        {"LACLAUGPT_FIREFOX_COMMAND": "powershell.exe -NoProfile -Command firefox"}
    )
    assert command == ["powershell.exe", "-NoProfile", "-Command", "firefox"]


def test_unrunnable_placeholder_is_not_accepted(monkeypatch) -> None:
    """A discovered-but-dead executable must fail loudly, not resolve quietly."""
    monkeypatch.setattr(brazil26_browser.shutil, "which", lambda name: "/usr/bin/firefox")
    monkeypatch.setattr(
        brazil26_browser, "_is_runnable_executable", lambda executable: False
    )

    assert brazil26_browser._resolve_firefox_executable({}) == ""
    try:
        brazil26_browser._firefox_command({})
    except RuntimeError as exc:
        assert "Firefox executable not found" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("a dead executable must raise")


def test_runnable_executable_detects_dead_placeholder(tmp_path: Path) -> None:
    # Direct probe of the guard: a script that exits non-zero is not runnable
    # (this is exactly how Ubuntu's firefox snap shim behaves).
    dead = tmp_path / "firefox"
    dead.write_text("#!/bin/sh\necho 'requires the firefox snap' >&2\nexit 1\n", encoding="utf-8")
    dead.chmod(0o755)
    assert brazil26_browser._is_runnable_executable(str(dead)) is False

    alive = tmp_path / "firefox-good"
    alive.write_text("#!/bin/sh\necho 'Mozilla Firefox 140.0'\nexit 0\n", encoding="utf-8")
    alive.chmod(0o755)
    assert brazil26_browser._is_runnable_executable(str(alive)) is True

    assert brazil26_browser._is_runnable_executable(str(tmp_path / "absent")) is False


def test_preflight_rejects_explicitly_unrunnable_browser(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """An explicitly configured executable that cannot run must be a problem."""
    repo = tmp_path / "repo"
    (repo / "browser/firefox").mkdir(parents=True)
    (repo / "browser/firefox/manifest.json").write_text("{}", encoding="utf-8")
    (repo / "data/config").mkdir(parents=True)
    (repo / "data/config/brazil26-localhost.env").write_text(
        "LACLAUGPT_PROJECT_ID=brazil26\n"
        "LACLAUGPT_FIREFOX_COMMAND=/usr/bin/firefox\n",
        encoding="utf-8",
    )
    config = tmp_path / "brazil.yaml"
    config.write_text("study: brazil26\n", encoding="utf-8")

    monkeypatch.setattr(
        brazil26_browser, "load_config", lambda _path: SimpleNamespace(study="brazil26")
    )
    monkeypatch.setattr(
        brazil26_browser, "_is_runnable_executable", lambda executable: False
    )
    monkeypatch.setenv("LACLAUGPT_ENV_FILE", str(repo / "data/config/brazil26-localhost.env"))

    assert (
        brazil26_browser.run_preflight(
            study_config=config,
            data_root=repo / "data",
            require_browser=True,
            repo_root=repo,
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "invalid"
    assert payload["browser_command"] == []
    assert any("not runnable" in problem for problem in payload["problems"])


def test_preflight_reports_no_runnable_browser_as_problem(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """On Ubuntu with no usable Firefox, discovery must not report ok."""
    repo = tmp_path / "repo"
    (repo / "browser/firefox").mkdir(parents=True)
    (repo / "browser/firefox/manifest.json").write_text("{}", encoding="utf-8")
    (repo / "data/config").mkdir(parents=True)
    config = tmp_path / "brazil.yaml"
    config.write_text("study: brazil26\n", encoding="utf-8")

    monkeypatch.setattr(
        brazil26_browser, "load_config", lambda _path: SimpleNamespace(study="brazil26")
    )
    monkeypatch.setattr(brazil26_browser.shutil, "which", lambda name: "/usr/bin/firefox")
    monkeypatch.setattr(
        brazil26_browser, "_is_runnable_executable", lambda executable: False
    )
    monkeypatch.setenv("LACLAUGPT_ENV_FILE", str(tmp_path / "absent.env"))

    assert (
        brazil26_browser.run_preflight(
            study_config=config,
            data_root=repo / "data",
            require_browser=True,
            repo_root=repo,
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "invalid"
    assert payload["browser_command"] == []
    assert any("Firefox executable not found" in problem for problem in payload["problems"])
