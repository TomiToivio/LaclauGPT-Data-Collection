"""EU Commmission ``web_source`` dates: the spelled-month stamp (#362).

``web_fetch._published`` matches ``<time[^>]+datetime=`` and therefore hands this
parser the literal Commission stamp ``14 October 2026``. None of the numeric
formats in ``_SITE_DATE_FORMATS`` cover it, so every ``eu_ai_policy`` record was
stored with ``handoff.published_at = null`` and, because the study requires a
source publication time for analysis, could never be analysed.

These contracts pin the production string, the handoff it must reach, and the
fact that a stamp which is genuinely unusable is still counted rather than
silently accepted by a looser matcher.
"""
from __future__ import annotations

from datetime import UTC, datetime

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

# The exact string the live page emits inside ``<time datetime="...">``; captured
# from https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai
EU_STRING = "14 October 2026"
# The same family as published on other Commission pages: zero-padded day.
EU_PADDED_STRING = "05 October 2026"
# Refused on purpose: a month and a year without a day is not a publication date.
REJECTED_STRING = "October 2026"


def _eu_record(created_at: str = EU_STRING) -> NormalizedRecord:
    record = NormalizedRecord(
        source_url="https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai",
        platform="web",
        text="Regulatory framework for AI",
        timestamp=created_at,
        raw_payload={},
        collection_provenance=CollectionProvenance(module="external-link-fetcher"),
    )
    record.source.raw_metadata["source_name"] = "eu_ai_policy"
    return record


def test_the_commission_stamp_parses_to_the_published_date():
    parsed = parse_source_time(EU_STRING)
    assert parsed == datetime(2026, 10, 14, tzinfo=UTC)
    assert parsed is not None and parsed.isoformat() == "2026-10-14T00:00:00+00:00"


def test_the_zero_padded_day_is_the_same_date():
    assert parse_source_time(EU_PADDED_STRING) == datetime(2026, 10, 5, tzinfo=UTC)


def test_the_eu_record_reaches_the_handoff_with_a_publication_time():
    payload = _eu_record().model_dump(mode="json")

    assert source_publication_time(payload) == datetime(2026, 10, 14, tzinfo=UTC)
    assert analysis_eligibility(payload, RealtimePolicy.ai26()) == (True, "eligible")
    assert build_handoff(payload, project_id="ai26")["published_at"] == "2026-10-14T00:00:00+00:00"


def test_a_date_without_a_day_is_still_refused_and_counted():
    records = [_eu_record(REJECTED_STRING)]

    assert parse_source_time(REJECTED_STRING) is None
    assert unparsed_source_time_counts(records) == {"eu_ai_policy": 1}
    warning = unparsed_source_time_warning(records)
    assert warning is not None
    assert "eu_ai_policy=1" in warning


def test_parsed_eu_records_do_not_warn():
    records = [_eu_record()]

    assert unparsed_source_time_counts(records) == {}
    assert unparsed_source_time_warning(records) is None
