"""Pins the future-publication guard (#369).

Three analysis-grade rows carried publication times ahead of their own capture. Two were
event pages whose *start date* had been read as a publication date; the third was a
date-only stamp one day ahead. The study window would have admitted all three.
"""
from datetime import datetime, timedelta, timezone

from laclaugpt_data_collection.handoff import (
    MAX_PUBLICATION_AHEAD,
    build_handoff,
    capture_time,
    publication_is_plausible,
)

CAPTURED = datetime(2026, 10, 27, 14, 4, tzinfo=timezone.utc)


def _record(published: str) -> dict:
    return {
        "collection_id": "ai26",
        "project_id": "ai26",
        "source_url": "https://example.invalid/events/thing",
        "source": {"platform": "rss", "published_at": published},
        "content": {"text": "An event listing with a date in its body."},
        "provenance": [{"metadata": {"captured_at": CAPTURED.isoformat()}}],
    }


def test_an_event_start_date_a_month_ahead_is_refused():
    handoff = build_handoff(_record("2026-12-01T12:00:00+00:00"))
    assert handoff["status"] == "excluded"
    assert handoff["reason"] == "published_after_capture"


def test_a_date_only_stamp_one_day_ahead_is_tolerated():
    handoff = build_handoff(_record("2026-10-28T00:00:00+00:00"))
    assert handoff["status"] != "excluded"


def test_an_ordinary_publication_time_is_unaffected():
    handoff = build_handoff(_record("2026-10-20T09:00:00+00:00"))
    assert handoff["status"] != "excluded"


def test_a_missing_capture_time_is_not_treated_as_a_defect():
    assert publication_is_plausible(CAPTURED + timedelta(days=40), None) is True


def test_a_missing_publication_time_is_not_treated_as_a_defect():
    assert publication_is_plausible(None, CAPTURED) is True


def test_the_tolerance_is_two_days():
    assert MAX_PUBLICATION_AHEAD == timedelta(days=2)
    edge = CAPTURED + MAX_PUBLICATION_AHEAD
    assert publication_is_plausible(edge, CAPTURED) is True
    assert publication_is_plausible(edge + timedelta(seconds=1), CAPTURED) is False


def test_capture_time_reads_provenance_metadata():
    assert capture_time(_record("2026-10-20T09:00:00+00:00")) == CAPTURED


def test_capture_time_falls_back_to_the_record():
    record = _record("2026-10-20T09:00:00+00:00")
    record["provenance"] = []
    record["collected_at"] = CAPTURED.isoformat()
    assert capture_time(record) == CAPTURED
