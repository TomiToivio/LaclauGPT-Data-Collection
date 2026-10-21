"""The visible half of the ETUI date defect (#295).

The parser gap itself is fixed on `main` (`_SITE_DATE_FORMATS` in `realtime.py`):
`Thu, 10/08/2026 - 13:30` now parses. What that fix does not do is make the *next*
rejected stamp visible. `parse_source_time` returns `None`, `build_handoff` writes
`published_at = null`, and because the study declares
`source_publication_time_required_for_analysis`, the row can never be analysed --
all 7 (now 8) ETUI rows in the live store reached exactly that state without a
single line of output saying so.

These contracts pin the counting warning and the fact that the production string
no longer triggers it.
"""
from __future__ import annotations

from datetime import UTC, datetime

from laclaugpt_data_collection import server_runner
from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord
from laclaugpt_data_collection.realtime import (
    RealtimePolicy,
    analysis_eligibility,
    parse_source_time,
    source_publication_time,
    unparsed_source_time_counts,
    unparsed_source_time_warning,
)

# The exact string the ETUI feed emitted; visible in `source.created_at` of every
# stored etui record.
ETUI_STRING = "Thu, 10/08/2026 - 13:30"
# The same family, refused: day-first would make 10/08 ambiguous.
REJECTED_STRING = "Thu, 13/08/2026 - 13:30"


def _etui_record(created_at: str = ETUI_STRING) -> NormalizedRecord:
    record = NormalizedRecord(
        source_url="https://www.etui.org/publications/example",
        platform="rss",
        text="Example report",
        timestamp=created_at,
        raw_payload={},
        collection_provenance=CollectionProvenance(module="rss-feedparser"),
    )
    record.source.raw_metadata["source_name"] = "etui"
    return record


def test_the_production_string_still_parses_to_the_published_time():
    parsed = parse_source_time(ETUI_STRING)
    assert parsed == datetime(2026, 10, 8, 13, 30, tzinfo=UTC)
    assert parsed.isoformat() == "2026-10-08T13:30:00+00:00"


def test_the_etui_record_reaches_the_handoff_with_a_publication_time():
    payload = _etui_record().model_dump(mode="json")

    assert source_publication_time(payload) == datetime(2026, 10, 8, 13, 30, tzinfo=UTC)
    assert analysis_eligibility(payload, RealtimePolicy.ai26()) == (True, "eligible")
    assert build_handoff(payload, project_id="ai26")["published_at"] == "2026-10-08T13:30:00+00:00"


def test_a_month_invalid_numeric_stamp_is_rejected_not_raised():
    """`13/08/2026` matches the numeric shape but is not a month-first date.

    A rejected stamp must return None like every other unknown format. Raising
    from `parse_source_time` would fail the whole collection cycle over one bad
    publisher date, which is the opposite of "report it, do not make it fatal".
    """
    assert parse_source_time(REJECTED_STRING) is None
    assert parse_source_time("Thu, 00/00/2026 - 10:00") is None


def test_unparsed_source_time_is_counted_and_named():
    records = [_etui_record(), _etui_record(), _etui_record()]
    records[0].source.created_at = REJECTED_STRING
    records[1].source.created_at = REJECTED_STRING

    assert unparsed_source_time_counts(records) == {"etui": 2}
    warning = unparsed_source_time_warning(records)
    assert warning is not None
    assert "2 record(s)" in warning
    assert "etui=2" in warning


def test_parsed_etui_records_do_not_warn():
    records = [_etui_record()]
    assert unparsed_source_time_counts(records) == {}
    assert unparsed_source_time_warning(records) is None


def test_rss_cycle_reports_unparsed_dates_by_source_without_failing(monkeypatch):
    """The cycle keeps the records but names the source in a counted warning."""
    collected: list[str] = []
    real_collect = server_runner.collect_rss_records

    class Store:
        def upsert(self, record):
            collected.append(record.source_url)
            return True

    def recording_collect(*args, **kwargs):
        """Pass through to the real collector so the warning path is exercised."""
        return real_collect(*args, **kwargs)

    monkeypatch.setattr(server_runner, "load_feed_manifest", lambda _p: [
        {"name": "etui", "feed_url": "https://example.invalid/etui"}
    ])
    monkeypatch.setattr(server_runner, "collect_rss_records", recording_collect)

    class RSS:
        def __init__(self, urls, *, max_items_per_feed, source_name):
            self.source_name = source_name

        def collect(self):
            from laclaugpt_data_collection.collectors.base import CollectionResult

            result = CollectionResult(requests_seen=1, bodies_seen=1, raw_items_seen=2)
            result.records = [_etui_record(), _etui_record(REJECTED_STRING)]
            return result

    monkeypatch.setattr(server_runner, "RSSCollector", RSS)
    from laclaugpt_data_collection import factory

    monkeypatch.setattr(factory, "build_record_store", lambda settings: Store())

    settings = Settings(_env_file=None, project_id="brazil26", record_backend="csv")
    summary = server_runner.run_phase1_rss(
        settings,
        study_config="unused.yaml",
        source_manifest="synthetic.toml",
        collection_id="brazil26",
        rotation=0,
    )

    assert summary["status"] == "ok", "an unparseable date must not fail the cycle"
    assert summary["records_synced"] == 2, "both records are still stored"
    assert any("etui=1" in warning for warning in summary["warnings"])
    assert any("unparseable source publication time" in warning for warning in summary["warnings"])
