"""Regression coverage for issue #174 Firefox/WSL readiness."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from laclaugpt_data_collection import brazil26_browser as browser


def test_spaced_executable_path_is_single_argument(tmp_path: Path) -> None:
    executable = tmp_path / "Program Files" / "Mozilla Firefox" / "firefox.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    assert browser._firefox_command({"LACLAUGPT_FIREFOX_COMMAND": str(executable)}) == [
        str(executable)
    ]


def test_quoted_executable_with_options_and_profile() -> None:
    env = {
        "LACLAUGPT_FIREFOX_COMMAND": "'/mnt/c/Program Files/Mozilla Firefox/firefox.exe' --new-instance",
        "LACLAUGPT_FIREFOX_PROFILE": "Brazil26 Research",
    }
    assert browser._firefox_command(env) == [
        "/mnt/c/Program Files/Mozilla Firefox/firefox.exe",
        "--new-instance",
        "-P",
        "Brazil26 Research",
    ]


def test_preflight_probe_rejects_broken_snap_shim(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "firefox"
    executable.touch()
    monkeypatch.setattr(
        browser.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )
    with pytest.raises(RuntimeError, match="unusable"):
        browser._check_firefox_command([str(executable)], env={})


def test_preflight_probe_accepts_working_executable(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "firefox"
    executable.touch()
    seen = []
    def probe(args, **kwargs):
        seen.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(browser.subprocess, "run", probe)
    browser._check_firefox_command([str(executable), "-P", "Brazil26"], env={})
    assert seen == [[str(executable), "-P", "Brazil26", "--version"]]


def test_preflight_probe_reports_timeout(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "firefox"
    executable.touch()
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("firefox", 8)
    monkeypatch.setattr(browser.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="failed its --version probe"):
        browser._check_firefox_command([str(executable)], env={})


def test_preflight_probe_checks_wrapper_target(tmp_path: Path, monkeypatch) -> None:
    """A working wrapper cannot hide a missing downstream Firefox target."""
    wrapper = tmp_path / "env"
    wrapper.touch()
    seen = []
    def probe(args, **kwargs):
        seen.append(args)
        return SimpleNamespace(returncode=127)
    monkeypatch.setattr(browser.subprocess, "run", probe)
    with pytest.raises(RuntimeError, match="unusable"):
        browser._check_firefox_command(
            [str(wrapper), "missing-firefox", "-P", "Brazil26"], env={}
        )
    assert seen == [[str(wrapper), "missing-firefox", "-P", "Brazil26", "--version"]]
