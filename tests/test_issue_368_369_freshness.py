"""Regression tests for #368 and #369. No private records or network."""
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.realtime import RealtimePolicy, analysis_eligibility

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_ai26_capture_freshness.py"
spec = importlib.util.spec_from_file_location("ai26_freshness", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_future_event_timestamp_is_not_analysis_ready():
    future = (datetime.now(UTC) + timedelta(days=40)).isoformat()
    rec = {"collection_id": "ai26", "source_url": "https://example.org/events/future",
           "source": {"platform": "rss", "created_at": future}}
    assert analysis_eligibility(rec, RealtimePolicy.ai26()) == (
        False, "future_source_publication_time")
    handoff = build_handoff(rec, project_id="ai26")
    assert handoff["status"] == "excluded"
    assert handoff["reason"] == "future_source_publication_time"
    assert handoff["published_at"] == future


def test_date_only_near_current_day_is_not_rejected():
    rec = {"source": {"created_at": datetime.now(UTC).date().isoformat()}}
    assert analysis_eligibility(rec, RealtimePolicy.ai26())[0]


def test_stale_x_capture_fails_even_if_other_sources_healthy():
    now = datetime(2026, 10, 28, 12, tzinfo=UTC)
    report = module.evaluate({"x": "2026-10-26T14:54:37Z",
                              "rss": "2026-10-28T11:00:00Z"}, now=now)
    assert not report["ok"]
    assert report["failures"]["x"] == "stale_capture"


def test_missing_and_fresh_x():
    now = datetime(2026, 10, 28, 12, tzinfo=UTC)
    assert module.evaluate({}, now=now)["failures"]["x"] == "no_capture"
    assert module.evaluate({"x": "2026-10-28T11:00:00Z"}, now=now)["ok"]
