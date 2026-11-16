"""The AI26 localhost readiness report (issue #433).

The report's whole purpose is to keep three states apart: a verified data plane, a failed service,
and a browser step that is waiting on a human. These tests pin that separation, and pin that the
report never turns BLOCKED into PASS on its own.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ai26_localhost_readiness.py"


def _module():
    spec = importlib.util.spec_from_file_location("ai26_localhost_readiness", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def statuses(results) -> dict[str, str]:
    return {item["check"]: item["status"] for item in results}


def test_a_missing_backend_is_a_failure_not_a_silence():
    module = _module()
    results = module.capture_endpoint_findings(None, "http://127.0.0.1:8766/status")
    assert results[0]["status"] == module.FAIL
    assert "no JSON" in results[0]["detail"]


def test_a_live_backend_reports_what_it_has_seen():
    module = _module()
    payload = {"active": True, "study": "ai26", "seen_total": 2837,
               "stats": {"captures": 0, "errors": 0}}
    results = module.capture_endpoint_findings(payload, "http://example.invalid/status")
    found = statuses(results)
    assert found["capture backend"] == module.PASS
    assert found["capture backend is active"] == module.PASS
    assert found["capture backend has seen traffic"] == module.PASS


def test_a_backend_serving_another_study_fails():
    module = _module()
    results = module.capture_endpoint_findings({"active": True, "study": "brazil26"}, "http://x")
    assert statuses(results)["capture backend serves AI26"] == module.FAIL


def test_an_inactive_backend_fails_even_when_it_answers():
    module = _module()
    results = module.capture_endpoint_findings({"active": False, "study": "ai26"}, "http://x")
    assert statuses(results)["capture backend is active"] == module.FAIL


def test_the_browser_handoff_stays_blocked_until_the_operator_says_otherwise(tmp_path):
    module = _module()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    blocked = statuses(module.firefox_findings(manifest, firefox_ready=False))
    assert blocked["browser capture handoff"] == module.BLOCKED
    ready = statuses(module.firefox_findings(manifest, firefox_ready=True))
    assert ready["browser capture handoff"] == module.PASS


def test_a_missing_extension_manifest_is_a_failure(tmp_path):
    module = _module()
    results = module.firefox_findings(tmp_path / "absent.json", firefox_ready=False)
    assert statuses(results)["capture extension manifest"] == module.FAIL


def test_missing_environment_variables_are_named_but_not_printed(monkeypatch):
    module = _module()
    monkeypatch.delenv("LACLAUGPT_MONGODB_URI", raising=False)
    monkeypatch.setenv("LACLAUGPT_REDIS_URL", "redis://hidden.invalid:6379/0")
    results = module.environment_findings(("LACLAUGPT_MONGODB_URI", "LACLAUGPT_REDIS_URL"))
    assert results[0]["status"] == module.FAIL
    assert "LACLAUGPT_MONGODB_URI" in results[0]["detail"]
    assert "hidden.invalid" not in json.dumps(results)


def test_the_probe_tries_the_bind_host_after_loopback(monkeypatch):
    module = _module()
    monkeypatch.setenv("AI26_BIND_HOST", "100.64.0.1")
    urls = module.candidate_urls(None)
    assert urls[0] == "http://127.0.0.1:8766/status"
    assert "http://100.64.0.1:8766/status" in urls
    assert len(urls) == len(set(urls))


def test_an_explicit_url_is_tried_first(monkeypatch):
    module = _module()
    urls = module.candidate_urls("http://127.0.0.1:9999/status")
    assert urls[0] == "http://127.0.0.1:9999/status"


def test_a_failed_service_is_reported_with_the_scope_that_answered(monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "service_state", lambda unit: ("failed", "user"))
    results = module.service_findings("ai26-export.service")
    assert results[0]["status"] == module.FAIL
    assert "failed" in results[0]["detail"] and "user" in results[0]["detail"]


def test_blocked_alone_does_not_fail_the_run(monkeypatch, tmp_path, capsys):
    """A waiting handoff is a state, not an error: the exit status is for real failures."""
    module = _module()
    monkeypatch.setattr(module, "_read_json", lambda url, timeout=5.0: {"active": True, "study": "ai26"})
    monkeypatch.setattr(module, "service_state", lambda unit: ("active", "user"))
    # CI has no Firefox and no profile: the fixture supplies both so the test measures the exit
    # contract rather than the runner's installed software.
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/firefox")
    profiles = tmp_path / "profiles.ini"
    profiles.write_text("[Profile0]\nPath=abc.default\n", encoding="utf-8")
    monkeypatch.setattr(module, "PROFILE_PATTERNS", (str(profiles),))
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("LACLAUGPT_MONGODB_URI", "mongodb://hidden.invalid")
    monkeypatch.setenv("LACLAUGPT_REDIS_URL", "redis://hidden.invalid")
    monkeypatch.setenv("LACLAUGPT_PROJECT_ID", "ai26")
    code = module.main(["--extension-manifest", str(manifest), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0, "only BLOCKED, nothing failed"
    assert payload["summary"]["blocked"] == 1
    assert payload["summary"]["fail"] == 0
