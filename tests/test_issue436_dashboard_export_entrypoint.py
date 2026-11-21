"""#436: the dashboard export has an entry point a current repository owns.

The five-week failure was not a bug in the export loop — it was a unit pointing at an archived repository,
with a log path that silently swallowed the error and a pre-run truncation that turned a failed export into
an empty dashboard.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "export_ai26_dashboard_jsonl.py"
spec = importlib.util.spec_from_file_location("export_ai26_dashboard_jsonl", MODULE)
export_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_module)
resolve_runtime = export_module.resolve_runtime


def _runtime_with(tmp_path: Path, name: str = "runtime") -> Path:
    runtime = tmp_path / name
    runtime.mkdir(parents=True)
    (runtime.parent / "laclaugpt").mkdir(exist_ok=True)
    (runtime.parent / "laclaugpt" / "__init__.py").write_text("", encoding="utf-8")
    return runtime


def test_an_explicit_runtime_wins(tmp_path):
    runtime = _runtime_with(tmp_path, "explicit")
    assert resolve_runtime(str(runtime), {}, defaults=()) == runtime


def test_the_environment_names_the_runtime_when_no_flag_is_given(tmp_path):
    runtime = _runtime_with(tmp_path, "from-env")
    assert resolve_runtime(None, {"LACLAUGPT_AI26_RUNTIME": str(runtime)}, defaults=()) == runtime


def test_a_directory_that_is_not_a_runtime_is_not_accepted(tmp_path):
    empty = tmp_path / "not-a-runtime"
    empty.mkdir()
    with pytest.raises(SystemExit) as failure:
        resolve_runtime(str(empty), {"LACLAUGPT_AI26_RUNTIME": str(empty)}, defaults=())
    # The message names what was checked, so an operator can see why the unit will not start.
    assert "not-a-runtime" in str(failure.value)
