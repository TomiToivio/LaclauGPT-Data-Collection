"""Regression tests for #202: a valid-but-empty feed must name its source.

Two configured P1 AI26 feeds (data_society, ada_lovelace) serve well-formed
RSS 2.0 documents with zero <item> entries. Because collection warnings are
aggregated anonymously, the cycle log could not say which source was empty,
and the generic "check endpoint/payload drift" hint pointed at a parser bug
that does not exist. These tests pin the new, named, distinct warning.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from laclaugpt_data_collection.collectors.base import CollectionResult
from laclaugpt_data_collection.collectors.rss import RSSCollector


def _feedparser_stub(entries):
    def parse(_url: str):
        return SimpleNamespace(entries=entries)

    return SimpleNamespace(parse=parse)


def test_valid_empty_feed_warns_with_the_source_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "feedparser", _feedparser_stub([]))

    result = RSSCollector(
        ["https://datasociety.net/feed/"], source_name="data_society"
    ).collect()

    assert result.records == []
    # Fetched and parsed, but carried nothing.
    assert result.bodies_seen == 1
    assert result.raw_items_seen == 0
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.startswith("data_society: ")
    assert "contained no items" in warning
    # It must not masquerade as payload drift any more.
    assert "endpoint/payload drift" not in warning


def test_valid_empty_feed_without_a_name_still_reads_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "feedparser", _feedparser_stub([]))

    result = RSSCollector(["https://example.invalid/feed"]).collect()

    assert len(result.warnings) == 1
    assert result.warnings[0].startswith("response body captured but the feed contained no items")


def test_empty_feed_warning_is_distinct_from_payload_drift() -> None:
    result = CollectionResult(bodies_seen=1, raw_items_seen=0)

    # The generic property still describes the drift case ...
    assert "endpoint/payload drift" in (result.zero_result_warning or "")
    # ... while the new one names the source and does not.
    named = result.empty_feed_warning("ada_lovelace")
    assert named.startswith("ada_lovelace: ")
    assert "endpoint/payload drift" not in named
    assert "endpoint/payload drift" not in result.empty_feed_warning()


def test_feed_with_items_produces_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = SimpleNamespace(link="https://example.invalid/a", title="t", summary="s")
    monkeypatch.setitem(sys.modules, "feedparser", _feedparser_stub([entry]))

    result = RSSCollector(["https://example.invalid/feed"], source_name="has_items").collect()

    assert len(result.records) == 1
    assert result.warnings == []
