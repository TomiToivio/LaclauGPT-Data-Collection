from __future__ import annotations

from pathlib import Path

from laclaugpt_data_collection.ai26_laskin_runner import run_phase1_laskin
from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord


class FakeSink:
    last = None

    def __init__(self, settings):
        self.settings = settings
        self.records = []
        self.notification_errors = []
        FakeSink.last = self

    def assert_private_config(self, study_config):
        return Path(study_config)

    def ingest(self, payload):
        self.records.append(payload)


def test_issue_172_laskin_runner_stamps_agent_execution_provenance(monkeypatch, tmp_path: Path) -> None:
    record = NormalizedRecord(
        document_id="agent-record",
        platform="web",
        timestamp="2026-09-22T05:00:00Z",
        source_url="https://example.org/agent-record",
        text="agent record",
        raw_payload={},
        collection_provenance=CollectionProvenance(module="issue-172-test"),
    )

    monkeypatch.setattr(
        "laclaugpt_data_collection.ai26_laskin_runner.load_non_browser_jobs",
        lambda _path: [{"kind": "web_source", "name": "synthetic", "priority": "P1"}],
    )
    monkeypatch.setattr(
        "laclaugpt_data_collection.ai26_laskin_runner.preflight_optional_dependencies",
        lambda _jobs: [],
    )
    monkeypatch.setattr(
        "laclaugpt_data_collection.ai26_laskin_runner.run_phase1_rss",
        lambda *args, **kwargs: {
            "records_synced": 0,
            "skipped_before_publication_floor": 0,
            "warnings": [],
            "errors": [],
            "notification_errors": [],
        },
    )
    monkeypatch.setattr(
        "laclaugpt_data_collection.ai26_laskin_runner._records_for_job",
        lambda *args, **kwargs: ([record], []),
    )
    monkeypatch.setattr(
        "laclaugpt_data_collection.ai26_laskin_runner.DistributedCaptureSink",
        FakeSink,
    )

    settings = Settings(
        _env_file=None,
        project_id="ai26",
        caller="hermes-agent",
        execution="agent",
        run_id="hermes-run-172",
    )
    summary = run_phase1_laskin(
        settings,
        study_config=tmp_path / "ai26.yaml",
        source_manifest=tmp_path / "ai26.sources.toml",
        collection_id="ai26",
        max_feeds=1,
        max_jobs=1,
        per_source_limit=1,
        limit=1,
        rotation=0,
    )

    assert summary["records_synced"] == 1
    assert FakeSink.last is not None
    provenance = FakeSink.last.records[0]["provenance"][-1]
    assert provenance["metadata"]["caller"] == "hermes-agent"
    assert provenance["metadata"]["execution"] == "agent"
    assert provenance["run_id"] == "hermes-run-172"


def test_issue_172_wrapper_preserves_explicit_caller_override() -> None:
    wrapper = (
        Path(__file__).resolve().parents[1] / "scripts" / "run_ai26_laskin_collect.sh"
    ).read_text(encoding="utf-8")

    assert "CALLER_OVERRIDE=${LACLAUGPT_CALLER-}" in wrapper
    assert "EXECUTION_OVERRIDE=${LACLAUGPT_EXECUTION-}" in wrapper
    assert 'export LACLAUGPT_CALLER="$CALLER_OVERRIDE"' in wrapper
    assert 'export LACLAUGPT_EXECUTION="$EXECUTION_OVERRIDE"' in wrapper
