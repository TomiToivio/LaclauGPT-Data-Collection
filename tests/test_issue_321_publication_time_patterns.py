"""Issue #321 follow-up: the article route needs the dates pages actually publish.

``fetch_web_child`` read a publication time only from the OpenGraph/meta form
(``article:published_time`` … ``content="…"``). Pages that instead expose the date
through JSON-LD — which is what Next.js, most CMS themes and Google's own blog do —
came back with ``source.created_at = None``, so #321's article route produced
undated children and the handoff excluded them.

These tests pin the three shapes and the precedence between them. All offline: the
parser takes HTML, no fetch is involved.
"""
from __future__ import annotations

from laclaugpt_data_collection.web_fetch import _published


def test_open_graph_meta_is_still_read() -> None:
    html = '<meta property="article:published_time" content="2026-10-20T09:00:00Z">'
    assert _published(html) == "2026-10-20T09:00:00Z"


def test_json_ld_date_published_is_read() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@type":"BlogPosting","datePublished":"2026-09-30T12:00:00Z"}'
        "</script>"
    )
    assert _published(html) == "2026-09-30T12:00:00Z"


def test_time_element_datetime_is_read() -> None:
    html = '<article><time datetime="2026-08-01T07:30:00+03:00">1 Aug 2026</time></article>'
    assert _published(html) == "2026-08-01T07:30:00+03:00"


def test_open_graph_wins_when_a_page_offers_several() -> None:
    html = (
        '<meta property="article:published_time" content="2026-10-20T09:00:00Z">'
        '{"datePublished":"2020-01-01T00:00:00Z"}'
        '<time datetime="2019-01-01T00:00:00Z">old</time>'
    )
    assert _published(html) == "2026-10-20T09:00:00Z"


def test_a_page_without_any_date_stays_undated() -> None:
    assert _published("<html><body><p>no date here</p></body></html>") is None
