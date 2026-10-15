"""Regression coverage for AI26 tick budget starvation (#273)."""
from pathlib import Path

from laclaugpt_data_collection import ai26_laskin_runner as runner
from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord


def test_rss_resync_cannot_starve_non_browser_p1(monkeypatch, tmp_path: Path):
    rss_limits = []
    attempted = []

    class Sink:
        notification_errors = []
        def __init__(self, settings):
            pass
        def assert_private_config(self, path):
            pass
        def ingest_with_status(self, payload):
            return payload, False  # repeat record: an update, not a new item

    jobs = [{"kind": "web_source", "name": f"p1_{i}", "priority": "P1"}
            for i in range(6)]
    monkeypatch.setattr(runner, "DistributedCaptureSink", Sink)
    monkeypatch.setattr(runner, "load_non_browser_jobs", lambda path: jobs)
    monkeypatch.setattr(runner, "preflight_optional_dependencies", lambda jobs: [])
    def rss(*args, **kwargs):
        rss_limits.append(kwargs["limit"])
        return {"records_synced": kwargs["limit"], "records_new": 0}
    monkeypatch.setattr(runner, "run_phase1_rss", rss)
    def collect(row, **kwargs):
        attempted.append(row["name"])
        record = NormalizedRecord(
            source_url=f"https://example.org/{row['name']}", platform="web",
            text="sample", timestamp="2026-10-15T00:00:00Z", raw_payload={},
            collection_provenance=CollectionProvenance(module="test"),
        )
        return [record], []
    monkeypatch.setattr(runner, "_records_for_job", collect)

    result = runner.run_phase1_laskin(
        Settings(_env_file=None, project_id="ai26"),
        study_config=tmp_path / "study.yaml",
        source_manifest=tmp_path / "sources.toml",
        rotation=0, limit=40, max_jobs=6, per_source_limit=5,
    )
    assert rss_limits == [20]
    assert len(attempted) == 6
    assert result["rss_records_synced"] == 20
    assert result["non_browser_records_synced"] == 6
    assert result["records_synced"] == 26
    assert result["tick_budget"]["non_browser_reserved"] == 20
    assert result["tick_budget"]["unused"] == 14
    assert result["tick_budget"]["jobs_admitted"] == attempted
    assert result["tick_budget"]["jobs_deferred"] == []
    assert result["deferred_by_tick_limit"] == 0
    assert result["deferred_by_source_budget"] == 0
    assert result["records_new"] == 0
    assert result["records_updated"] == 26


def test_zero_non_browser_jobs_preserves_full_rss_budget(monkeypatch, tmp_path: Path):
    limits = []
    class Sink:
        notification_errors = []
        def __init__(self, settings):
            pass
        def assert_private_config(self, path):
            pass
    monkeypatch.setattr(runner, "DistributedCaptureSink", Sink)
    monkeypatch.setattr(runner, "load_non_browser_jobs", lambda path: [])
    monkeypatch.setattr(runner, "run_phase1_rss", lambda *a, **kw: (
        limits.append(kw["limit"]) or {"records_synced": 40, "records_new": 0}
    ))
    result = runner.run_phase1_laskin(
        Settings(_env_file=None, project_id="ai26"),
        study_config=tmp_path / "study.yaml",
        source_manifest=tmp_path / "sources.toml",
        rotation=0, limit=40,
    )
    assert limits == [40]
    assert result["tick_budget"]["non_browser_reserved"] == 0
    assert result["records_synced"] == 40
