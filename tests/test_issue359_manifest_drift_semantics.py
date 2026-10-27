"""Runtime drift comparison (#359): byte identity, then identity sets.

The gate exists to prove the running collector matches the tracked plan. A raw-byte comparison is
stricter than the deploy tool it guards -- that tool's own drift field reports `in_sync` at 84/84
planned sources -- so one deliberate private `active` toggle on one source made the line read STALE
forever, and a check that is always red stops carrying signal.

The rule now: **same identities, different field values** is a private override and passes, naming the
field. **Added or removed sources** is drift and fails, because that is a coverage change.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "scripts" / "check_ai26_runtime.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_ai26_runtime", SPEC)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_ai26_runtime"] = module
    spec.loader.exec_module(module)
    return module


runtime = _load()

BASE = '''[[web_source]]
name = "alpha"
active = true
priority = "P1"

[[web_source]]
name = "beta"
active = true
priority = "P1"
'''


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class TestSemanticDrift:
    def test_a_private_field_toggle_is_not_drift(self, tmp_path):
        tracked = write(tmp_path, "tracked.toml", BASE)
        deployed = write(tmp_path, "deployed.toml", BASE.replace(
            'name = "beta"\nactive = true', 'name = "beta"\nactive = false'))
        added, removed, changed = runtime.semantic_drift(tracked, deployed)
        assert (added, removed) == ([], [])
        assert changed == ["web_source:beta"]

    def test_a_removed_source_is_drift(self, tmp_path):
        tracked = write(tmp_path, "tracked.toml", BASE)
        deployed = write(tmp_path, "deployed.toml", BASE.replace('''[[web_source]]
name = "beta"
active = true
priority = "P1"
''', ""))
        added, removed, changed = runtime.semantic_drift(tracked, deployed)
        assert removed == ["web_source:beta"]
        assert added == []

    def test_an_added_source_is_drift(self, tmp_path):
        tracked = write(tmp_path, "tracked.toml", BASE)
        deployed = write(tmp_path, "deployed.toml", BASE + '''
[[web_source]]
name = "gamma"
active = true
''')
        added, removed, _ = runtime.semantic_drift(tracked, deployed)
        assert added == ["web_source:gamma"]
        assert removed == []

    def test_an_unparseable_file_returns_none_rather_than_pretending(self, tmp_path):
        tracked = write(tmp_path, "tracked.toml", "not = valid = toml [[[")
        deployed = write(tmp_path, "deployed.toml", BASE)
        assert runtime.semantic_drift(tracked, deployed) is None


class TestCompareConfig:
    def test_identical_files_pass(self, tmp_path):
        tracked = write(tmp_path, "tracked.toml", BASE)
        deployed = write(tmp_path, "deployed.toml", BASE)
        finding = runtime.compare_config("ai26.sources.toml", tracked, deployed)
        assert finding.ok is True
        assert finding.detail.startswith("sha256")

    def test_a_private_toggle_passes_and_names_the_field(self, tmp_path):
        tracked = write(tmp_path, "tracked.toml", BASE)
        deployed = write(tmp_path, "deployed.toml", BASE.replace(
            'name = "beta"\nactive = true', 'name = "beta"\nactive = false'))
        finding = runtime.compare_config("ai26.sources.toml", tracked, deployed)
        assert finding.ok is True, "a deliberate private override is not drift"
        assert "private override" in finding.detail
        assert "web_source:beta" in finding.detail

    def test_a_removed_source_still_fails(self, tmp_path):
        tracked = write(tmp_path, "tracked.toml", BASE)
        deployed = write(tmp_path, "deployed.toml", BASE.replace('''[[web_source]]
name = "beta"
active = true
priority = "P1"
''', ""))
        finding = runtime.compare_config("ai26.sources.toml", tracked, deployed)
        assert finding.ok is False
        assert "removed" in finding.detail

    def test_a_missing_deployment_still_fails(self, tmp_path):
        tracked = write(tmp_path, "tracked.toml", BASE)
        finding = runtime.compare_config("ai26.sources.toml", tracked, tmp_path / "absent.toml")
        assert finding.ok is False
        assert "not deployed" in finding.detail
