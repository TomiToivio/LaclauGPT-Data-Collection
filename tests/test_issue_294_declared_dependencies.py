"""Declared dependencies must be importable in the runtime that uses them (issue #294).

``langdetect`` is declared in pyproject's ``[feeds]`` extra and was absent from the Laskin venv.
``resolve_language`` then returned ``("", "detector_unavailable")`` -- indistinguishable from "this
text could not be classified" -- so the parliamentary arena collected 296 rows with an empty language
while the study declared ``languages: [en, fi]``, and no log line said why.

The runtime check now probes the declared imports so that failure is a reported line rather than a
silent blank. These contracts pin that behaviour, including the skip path (a checkout with no venv
must not be reported as broken).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_ai26_runtime.py"


def _module():
    # Register before exec: dataclasses resolves the defining module through sys.modules.
    import sys

    spec = importlib.util.spec_from_file_location("check_ai26_runtime", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_checkout(tmp_path: Path) -> Path:
    """A checkout whose `.venv/bin/python` is the interpreter running this test.

    That is what `compare_dependencies` probes, so the check can be exercised anywhere -- including
    CI, where the repository has no `.venv` of its own.
    """
    import sys

    bindir = tmp_path / ".venv" / "bin"
    bindir.mkdir(parents=True)
    # An exec launcher, not a symlink: a symlinked interpreter resolves sys.prefix from the
    # link's own directory and therefore loses the real environment's site-packages, which
    # would make this test fail for a reason that has nothing to do with the check.
    launcher = bindir / "python"
    launcher.write_text('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable, encoding="utf-8")
    launcher.chmod(0o755)
    return tmp_path


def test_langdetect_is_a_declared_probe():
    """The detector is the dependency whose absence was invisible, so it must be probed."""
    assert "langdetect" in _module().DECLARED_IMPORTS


def test_a_checkout_without_a_venv_is_skipped_not_failed(tmp_path):
    """CI installs into the runner environment; a missing .venv is not a runtime defect."""
    finding = _module().compare_dependencies(tmp_path)
    assert finding.ok
    assert "skipped" in finding.detail


def test_a_missing_declared_dependency_is_reported(tmp_path):
    checkout = _fake_checkout(tmp_path)
    finding = _module().compare_dependencies(checkout, imports=("definitely_not_installed_xyz",))
    assert not finding.ok
    assert "not importable" in finding.detail
    assert "definitely_not_installed_xyz" in finding.detail


def test_the_report_names_the_consequence_not_just_the_module(tmp_path):
    """A missing detector blanks labels silently; the line has to say so."""
    checkout = _fake_checkout(tmp_path)
    finding = _module().compare_dependencies(checkout, imports=("definitely_not_installed_xyz",))
    assert "blanks labels silently" in finding.detail
