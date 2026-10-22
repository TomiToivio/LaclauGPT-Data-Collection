"""Regression checks for #321 and #322."""
from __future__ import annotations

import pytest

from laclaugpt_data_collection.distributed_capture import DistributedCaptureSink
from laclaugpt_data_collection.web_discovery import _Links
from laclaugpt_data_collection.web_fetch import _published


def test_reject_hollow_capture_before_remote_io():
    # Bypass infrastructure initialization: the guard must fire BEFORE a remote call.
    sink = object.__new__(DistributedCaptureSink)
    sink.settings = type("SettingsStub", (), {"project_id": "ai26"})()
    shell = {
        "source_url": "https://x.com/PauseAI/status/2085033275710415126",
        "content": {"text": ""},
        "raw_capture": {"payload": None},
        "source": {"platform": ""},
    }
    with pytest.raises(ValueError, match="hollow_capture_rejected"):
        sink.ingest_with_status(shell)


def test_discovery_parser_finds_articles_and_rss():
    parser = _Links()
    parser.feed(
        '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
        '<a href="/news/dated-article">Story</a>'
    )
    assert parser.feeds == ["/feed.xml"]
    assert parser.articles == ["/news/dated-article"]


@pytest.mark.parametrize("html", [
    '<meta content="2026-10-22T10:00:00Z" property="article:published_time">',
    '<script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-10-22T10:00:00Z"}</script>',
])
def test_published_metadata(html):
    assert _published(html) == "2026-10-22T10:00:00Z"


def test_undated_page_stays_undated():
    assert _published("<html><title>Homepage</title></html>") is None
