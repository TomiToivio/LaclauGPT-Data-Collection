"""Publisher date stamps that neither ISO 8601 nor RFC 2822 can express (issue #295).

The etui feed renders its publication time as ``Tue, 10/20/2026 - 17:23``. Both standard parsers
reject that, so every etui record arrived undated, was treated as having no publication time, and
could never be placed by the publication floor. These contracts pin the added formats *and* the
refusal to guess: an ambiguous ``31/12/2026`` must stay unparsed rather than become a wrong date.
"""

from __future__ import annotations

from datetime import UTC, datetime

from laclaugpt_data_collection.realtime import parse_source_time


def test_the_etui_drupal_stamp_parses():
    parsed = parse_source_time("Tue, 10/20/2026 - 17:23")
    assert parsed == datetime(2026, 10, 20, 17, 23, tzinfo=UTC)


def test_a_second_etui_stamp_parses():
    assert parse_source_time("Thu, 10/15/2026 - 12:00") == datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def test_standard_formats_are_unchanged():
    assert parse_source_time("2026-10-20T17:23:00+00:00") == datetime(2026, 10, 20, 17, 23, tzinfo=UTC)
    assert parse_source_time("Tue, 20 Oct 2026 17:23:00 +0000") == datetime(
        2026, 10, 20, 17, 23, tzinfo=UTC
    )


def test_a_slash_date_that_cannot_be_month_first_is_not_guessed():
    """31/12/2026 is unambiguous only in day-first order; the parser must decline it.

    Silently reading it as month 31 would raise, but reading ``05/06/2026`` as May 6th when the
    publisher meant June 5th would be worse: a wrong date passes every downstream check.
    """
    assert parse_source_time("31/12/2026") is None


def test_empty_and_unparseable_values_stay_none():
    for value in (None, "", "   ", "sometime last week", "not-a-date"):
        assert parse_source_time(value) is None


def test_the_iso_path_still_wins_over_the_site_formats():
    """An ISO stamp is never re-read through a publisher format."""
    assert parse_source_time("2026-10-20") == datetime(2026, 10, 20, tzinfo=UTC)
