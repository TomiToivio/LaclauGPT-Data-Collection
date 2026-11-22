"""#457: the summary's dependency on a shell string must not be able to cost the summary.

Putting the drift verdict in the cycle summary made the summary depend on an environment
variable written by a shell script. An inline `json.loads` raises there, so a cycle that had
*already collected records* would lose its entire summary because of one malformed log line.
These tests pin the defensive parse: absent is None, malformed is stated, and the summary
never reaches for `json.loads` directly.
"""

from __future__ import annotations

import json
from pathlib import Path

from laclaugpt_data_collection.ai26_laskin_runner import runtime_drift_verdict

ROOT = Path(__file__).resolve().parents[1]


def test_the_verdict_is_parsed_from_the_wrapper_environment(monkeypatch):
    verdict = {"status": "stale_compatible", "stale": True, "blocking": False,
               "schema_changed_paths": []}
    monkeypatch.setenv("LACLAUGPT_AI26_RUNTIME_VERDICT_JSON", json.dumps(verdict))
    assert runtime_drift_verdict() == verdict


def test_an_absent_verdict_is_none_not_a_fabricated_in_sync(monkeypatch):
    """Absent means "the wrapper did not report", which is not the same as "in sync"."""
    monkeypatch.delenv("LACLAUGPT_AI26_RUNTIME_VERDICT_JSON", raising=False)
    assert runtime_drift_verdict() is None


def test_malformed_json_is_recorded_rather_than_raising(monkeypatch):
    monkeypatch.setenv("LACLAUGPT_AI26_RUNTIME_VERDICT_JSON", "{not json")
    assert runtime_drift_verdict() == {"verdict": "unparseable"}


def test_a_json_value_that_is_not_an_object_is_also_unparseable(monkeypatch):
    monkeypatch.setenv("LACLAUGPT_AI26_RUNTIME_VERDICT_JSON", '["stale"]')
    assert runtime_drift_verdict() == {"verdict": "unparseable"}


def test_the_summary_uses_the_guarded_helper():
    source = (ROOT / "src" / "laclaugpt_data_collection" / "ai26_laskin_runner.py").read_text(encoding="utf-8")
    assert '"runtime_drift": runtime_drift_verdict()' in source
    assert 'json.loads(os.environ.get("LACLAUGPT_AI26_RUNTIME_VERDICT_JSON")' not in source, (
        "an inline parse raises during summary construction"
    )


def test_the_helper_accepts_an_explicit_environment_for_testability():
    assert runtime_drift_verdict({"LACLAUGPT_AI26_RUNTIME_VERDICT_JSON": '{"stale": false}'}) == {"stale": False}
