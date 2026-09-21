"""Regression tests for issue #154: Laskin optional dependency contract."""
from __future__ import annotations

from pathlib import Path
import tomllib

from laclaugpt_data_collection import ai26_laskin_runner as runner

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "configs" / "studies" / "ai26.sources.example.toml"


def test_phase1_non_browser_extra_covers_source_specific_extras() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = project["project"]["optional-dependencies"]
    aggregate = set(extras["phase1-non-browser"])
    for name in ("feeds", "mastodon", "youtube", "documents", "bluesky-native"):
        assert set(extras[name]) <= aggregate, f"{name} drifted from phase1-non-browser"


def test_manifest_optional_job_kinds_have_a_dependency_contract() -> None:
    jobs = runner.load_non_browser_jobs(SOURCES)
    kinds = {str(job["kind"]) for job in jobs}
    assert {"mastodon_account", "youtube_source", "scholarly_query"} <= kinds
    assert {"mastodon_account", "youtube_source", "scholarly_query"} <= set(
        runner._OPTIONAL_DEPENDENCY_CONTRACT
    )


def test_preflight_reports_extra_and_job_kind(monkeypatch) -> None:
    monkeypatch.setattr(runner.importlib.util, "find_spec", lambda _name: None)
    jobs = [
        {"kind": "scholarly_query", "name": "frontier_ai_safety"},
        {"kind": "youtube_source", "name": "OpenAI"},
        {"kind": "mastodon_account", "name": "Timnit Gebru"},
    ]

    errors = runner.preflight_optional_dependencies(jobs)

    assert any("'documents'" in error and "'scholarly_query'" in error for error in errors)
    assert any("'youtube'" in error and "'youtube_source'" in error for error in errors)
    assert any("'mastodon'" in error and "'mastodon_account'" in error for error in errors)
    assert all("configured jobs:" in error and "missing modules:" in error for error in errors)


def test_laskin_docs_install_complete_non_browser_extra() -> None:
    runbook = (ROOT / "docs" / "AI26_LASKIN_COLLECTION.md").read_text(encoding="utf-8")
    handoff = (ROOT / "docs" / "HERMES_AI26_LASKIN_HANDOFF.md").read_text(encoding="utf-8")
    install = "pip install -e '.[distributed,phase1-non-browser]'"
    assert install in runbook
    assert install in handoff
    assert "pip install -e '.[distributed,feeds]'" not in runbook
    assert "pip install -e '.[distributed,feeds]'" not in handoff
