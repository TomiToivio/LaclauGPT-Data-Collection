"""Regression checks for AI26 issue #293 and ETUI issue #295."""
from datetime import UTC, datetime
from unittest.mock import patch

from laclaugpt_data_collection.realtime import parse_source_time


def test_etui_numeric_rss_date():
    assert parse_source_time("Thu, 10/08/2026 - 13:30") == datetime(2026, 10, 8, 13, 30, tzinfo=UTC)
    assert parse_source_time("Thu, 13/42/2026 - 13:30") is None


def test_existing_rfc_date():
    assert parse_source_time("Wed, 16 Sep 2026 10:00:00 GMT") == datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
