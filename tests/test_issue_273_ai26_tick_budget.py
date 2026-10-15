"""Regression: RSS re-sync must not starve non-browser P1 collection (#273)."""
from laclaugpt_data_collection import ai26_laskin_runner as runner
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord


class Settings:
    project_id = "ai26"
    caller = "test"
    execution = "test"
    run_id = None


class Sink:
    notification_errors = []

    def __init__(self, settings):
        self.records = self

    def assert_private_config(self, path):
        pass

    def ingest_with_status(self, payload):
        return payload, True


def test_rss_full_budget_cannot_starve_p1(monkeypatch, tmp_path):
    study = tmp_path / "study.yaml"
    study.write_text("study: ai26\n")
    requested = []

    def rss(*args, **kwargs):
        requested.append(kwargs["limit"])
        return {
            "records_synced": kwargs["limit"], "records_collected": 40,
            "records_new": 0, "warnings": [], "errors": [],
            "skipped_before_publication_floor": 0, "notification_errors": [],
        }

    def collect(row, **kwargs):
        return [NormalizedRecord(
            document_id="new", platform="web", source_url="https://example.org/new",
            text="fresh", raw_payload={},
            collection_provenance=CollectionProvenance(module="test"),
        )], []

    monkeypatch.setattr(runner, "load_non_browser_jobs", lambda path: [
        {"name": "priority_one", "kind": "web_source", "priority": "P1"}
    ])
    monkeypatch.setattr(runner, "preflight_optional_dependencies", lambda jobs: [])
    monkeypatch.setattr(runner, "run_phase1_rss", rss)
    monkeypatch.setattr(runner, "_records_for_job", collect)
    monkeypatch.setattr(runner, "DistributedCaptureSink", Sink)
    result = runner.run_phase1_laskin(
        Settings(), study_config=study, source_manifest=tmp_path / "sources.toml",
        limit=40, per_source_limit=5, max_jobs=1, rotation=0,
    )
    assert requested == [35]
    assert result["records_synced"] == 36
    assert result["non_browser_records_collected"] == 1
    assert result["source_outcomes"][0]["status"] == "ok"
    assert result["tick_budget"]["non_browser_reserved"] == 5
    assert result["tick_budget"]["admitted_jobs"] == ["priority_one"]
    assert result["tick_budget"]["deferred_jobs"] == []
    assert result["tick_budget"]["rss_synced"] == 35
    assert result["tick_budget"]["non_browser_synced"] == 1
    assert result["tick_budget"]["unused"] == 4
    assert result["records_updated"] == 35
