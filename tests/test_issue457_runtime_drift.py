"""#457: the runtime is the authority, so drift must be classified and recorded.

The wrapper detected a checkout two commits behind `origin/main`, then collected anyway --
by design, and reported it only in a log preamble. Two consequences: a merged fix never
reaches the records, and a schema-changing drift is indistinguishable from a harmless one.
This pins the three pieces that fix it: the schema-affecting classification, the verdict in
the cycle summary, and the fail-closed branch.
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their own module by name, so register it before executing.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runtime = _load("check_ai26_runtime", ROOT / "scripts" / "check_ai26_runtime.py")

from laclaugpt_data_collection.ai26_laskin_runner import runtime_drift_verdict  # noqa: E402


def test_schema_affecting_files_are_detected_by_name(tmp_path, monkeypatch):
    """Over-reporting is the safe direction: it refuses a cycle rather than writing old shape."""
    monkeypatch.setattr(runtime, "git", lambda *args, cwd: "\n".join([
        "src/laclaugpt_data_collection/models.py",
        "src/laclaugpt_data_collection/canonical.py",
        "src/laclaugpt_data_collection/analysis_schema_compat.py",
        "src/laclaugpt_data_collection/collectors/rss.py",
        "docs/README.md",
    ]))
    found = runtime.schema_affecting_changes(tmp_path, "aaa", "bbb")
    assert found == [
        "src/laclaugpt_data_collection/analysis_schema_compat.py",
        "src/laclaugpt_data_collection/canonical.py",
        "src/laclaugpt_data_collection/models.py",
    ]


def test_collector_only_drift_is_not_schema_affecting(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "git", lambda *args, cwd: "src/laclaugpt_data_collection/collectors/rss.py\ntests/x.py")
    assert runtime.schema_affecting_changes(tmp_path, "aaa", "bbb") == []


def test_a_finding_carries_the_classification():
    stale_compatible = runtime.Finding("code", False, "2 commit(s) behind", schema_affecting=False)
    stale_schema = runtime.Finding("code", False, "2 commit(s) behind", schema_affecting=True)
    assert stale_compatible.schema_affecting is False and stale_schema.schema_affecting is True


def test_the_cycle_summary_records_the_verdict(monkeypatch):
    """#457 item 1: queryable next to records_new, not only in the log preamble."""
    verdict = {"stale": True, "schema_affecting": False, "findings": []}
    monkeypatch.setenv("LACLAUGPT_RUNTIME_DRIFT_JSON", json.dumps(verdict))
    assert runtime_drift_verdict() == verdict


def test_an_absent_verdict_is_none_not_a_fabricated_ok(monkeypatch):
    monkeypatch.delenv("LACLAUGPT_RUNTIME_DRIFT_JSON", raising=False)
    assert runtime_drift_verdict() is None


def test_unparseable_verdict_is_stated_rather_than_swallowed(monkeypatch):
    monkeypatch.setenv("LACLAUGPT_RUNTIME_DRIFT_JSON", "{not json")
    assert runtime_drift_verdict() == {"verdict": "unparseable"}


def test_the_wrapper_fails_closed_only_on_schema_drift():
    """#457 item 3: the policy is explicit, and it is in the shell that enforces it."""
    wrapper = (ROOT / "scripts" / "run_ai26_laskin_collect.sh").read_text(encoding="utf-8")
    assert 'export LACLAUGPT_RUNTIME_DRIFT_JSON="$RUNTIME_JSON"' in wrapper
    assert "refusing to collect (fail-closed, #457)" in wrapper
    assert "exit 78" in wrapper
    assert "collecting anyway (verdict is in the cycle summary, #457)" in wrapper


def test_the_summary_object_lists_both_new_fields():
    source = (ROOT / "src" / "laclaugpt_data_collection" / "ai26_laskin_runner.py").read_text(encoding="utf-8")
    assert '"runtime_drift": runtime_drift_verdict()' in source
