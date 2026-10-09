"""Source failures must remain distinct from empty and budget-deferred polls."""
from pathlib import Path

import httpx
import pytest

from laclaugpt_data_collection import ai26_laskin_runner as runner
from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord
from laclaugpt_data_collection.web_fetch import fetch_web_child


def record():
    return NormalizedRecord(
        source_url="https://example.invalid/post", platform="web", text="synthetic",
        timestamp="2026-10-01T00:00:00Z", raw_payload={},
        collection_provenance=CollectionProvenance(module="synthetic-test"),
    )


def test_http_failure_has_status_without_echoing_url():
    outcome = fetch_web_child(
        "https://example.invalid/page?private=value", record(),
        transport=httpx.MockTransport(lambda request: httpx.Response(403)),
        host_validator=lambda url: True,
    )
    assert outcome.record is None
    assert outcome.status_code == 403
    assert outcome.error == "http_error"


def run_tick(monkeypatch, tmp_path, jobs, *, limit=10, rss_count=0):
    class Sink:
        notification_errors = []

        def __init__(self, settings):
            pass

        def assert_private_config(self, path):
            pass

        def ingest(self, payload):
            pass

    monkeypatch.setattr(runner, "DistributedCaptureSink", Sink)
    monkeypatch.setattr(runner, "load_non_browser_jobs", lambda path: jobs)
    monkeypatch.setattr(runner, "preflight_optional_dependencies", lambda jobs: [])
    monkeypatch.setattr(runner, "run_phase1_rss", lambda *a, **kw: {"records_synced": rss_count})
    return runner.run_phase1_laskin(
        Settings(_env_file=None, project_id="ai26"),
        study_config=tmp_path / "ai26.yaml", source_manifest=tmp_path / "sources.toml",
        rotation=0, max_jobs=len(jobs), limit=limit,
    )


def test_blocked_source_marks_tick_partial_and_continues(monkeypatch, tmp_path: Path):
    def fetch(url, parent, **kwargs):
        return fetch_web_child(
            url, parent, **kwargs,
            transport=httpx.MockTransport(lambda request: httpx.Response(403)),
            host_validator=lambda url: True,
        )

    monkeypatch.setattr(runner, "fetch_web_child", fetch)
    result = run_tick(monkeypatch, tmp_path, [
        {"kind": "web_source", "name": "synthetic_union", "priority": "P1",
         "url": "https://example.invalid/ai"},
        {"kind": "youtube_source", "name": "synthetic_video"},
    ])
    assert result["status"] == "partial"
    assert len(result["errors"]) == 2
    blocked, missing = result["source_outcomes"]
    assert blocked["status"] == "blocked"
    assert blocked["http_status"] == 403
    assert blocked["priority"] == "P1"
    assert missing["reason"] == "missing_video_urls"
    monkeypatch.setattr(runner, "run_phase1_laskin", lambda *a, **kw: result)
    assert runner.main(["--study-config", "unused", "--source-manifest", "unused"]) == 1


@pytest.mark.parametrize("rss_count,expected", [(0, ["ok", "deferred"]), (1, ["deferred", "deferred"])])
def test_budget_deferred_is_not_empty_or_failed(monkeypatch, tmp_path, rss_count, expected):
    calls = []

    def collect(row, **kwargs):
        calls.append(row["name"])
        return [record()], []

    monkeypatch.setattr(runner, "_records_for_job", collect)
    result = run_tick(monkeypatch, tmp_path, [
        {"kind": "web_source", "name": "first"},
        {"kind": "web_source", "name": "second"},
    ], limit=1, rss_count=rss_count)
    assert result["status"] == "ok"
    assert [o["status"] for o in result["source_outcomes"]] == expected
    assert len(calls) == 1 - rss_count


def test_successful_empty_poll_is_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "_records_for_job", lambda *a, **kw: ([], []))
    result = run_tick(monkeypatch, tmp_path, [{"kind": "web_source", "name": "empty"}])
    assert result["status"] == "ok"
    assert result["source_outcomes"][0]["status"] == "ok"
    assert result["source_outcomes"][0]["records_collected"] == 0
