"""Issue #321: a ``web_source`` must yield dated documents, not one undated snapshot.

The elite "blogs and manifestos" layer was structurally absent: 1 of 1 962
analysis-grade records came from a ``web_source``, because the runner knew two
hardcoded feed URLs and turned every other page into a single undated snapshot that
the handoff excludes.

The routes are pure HTML heuristics plus one bounded fetcher, so everything below is
offline: a mock transport serves the pages, the feed collector is a stub, and no test
touches the network.
"""
from __future__ import annotations

import httpx
import pytest

from laclaugpt_data_collection.web_source_discovery import (
    WebSourceError,
    collect_web_source,
    discover_article_urls,
    discover_feed_url,
)

BLOG = "https://labs.example.org/blog/"

_INDEX = """\
<html><head><title>Blog</title></head><body>
<nav><a href="/">Home</a><a href="/about">About us</a><a href="/careers">Careers</a></nav>
<main>
  <a href="/blog/2026/10/new-model-card">New model card for the frontier system</a>
  <a href="/blog/2026/09/safety-framework">Our safety framework, one year on</a>
  <a href="/blog/">Blog index</a>
</main></body></html>
"""

_ARTICLE = """\
<html><head>
<meta property="article:published_time" content="2026-10-20T09:00:00Z">
<title>New model card</title></head><body><p>body</p></body></html>
"""

_ARTICLE_JSONLD = """\
<html><head><script type="application/ld+json">
{"@type":"BlogPosting","datePublished":"2026-09-30T12:00:00Z"}
</script></head><body><p>body</p></body></html>
"""


def _any_host(url: str) -> bool:
    """The fetcher's DNS guard is production behaviour; offline it would fail."""
    return True


def _transport(pages: dict[str, str], *, status: dict[str, int] | None = None) -> httpx.MockTransport:
    """Serve ``pages`` by URL; unknown URLs are 404."""
    status = status or {}

    def handler(request: httpx.Request) -> httpx.Response:
        # The fetcher canonicalises before asking (trailing slash stripped), so match
        # on the slash-insensitive identity rather than the literal fixture key.
        url = str(request.url)
        identity = url.rstrip("/")
        for key, code in status.items():
            if key.rstrip("/") == identity:
                return httpx.Response(code, text="")
        for key, body in pages.items():
            if key.rstrip("/") == identity:
                return httpx.Response(200, text=body, headers={"content-type": "text/html"})
        return httpx.Response(404, text="missing")

    return httpx.MockTransport(handler)


class _FakeRSS:
    """Stands in for RSSCollector so the feed route never touches the network."""

    calls: list[list[str]] = []
    records: list[object] = []
    warnings: list[str] = []

    def __init__(self, feeds, max_items_per_feed=None):  # noqa: ANN001
        self.feeds = list(feeds)
        type(self).calls.append(self.feeds)

    def collect(self):  # noqa: ANN201
        from types import SimpleNamespace

        return SimpleNamespace(records=list(type(self).records), warnings=list(type(self).warnings))


def _feed_record():  # noqa: ANN201
    from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord

    return NormalizedRecord(
        document_id="feed-1",
        platform="web",
        source_url="https://labs.example.org/blog/post",
        text="feed body",
        raw_payload={"title": "feed post"},
        collection_provenance=CollectionProvenance(module="rss"),
    )


@pytest.fixture(autouse=True)
def _stub_feed_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeRSS.calls = []
    _FakeRSS.records = []
    _FakeRSS.warnings = []
    monkeypatch.setattr("laclaugpt_data_collection.web_source_discovery.RSSCollector", _FakeRSS)


# --------------------------------------------------------------------- discovery
def test_declared_feed_is_discovered_and_resolved() -> None:
    html = '<head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head>'
    assert discover_feed_url(html, BLOG) == "https://labs.example.org/feed.xml"


def test_atom_and_attribute_order_both_count() -> None:
    html = '<link type="application/atom+xml" href="https://other.example.org/atom" rel="alternate">'
    assert discover_feed_url(html, BLOG) == "https://other.example.org/atom"


def test_a_page_that_advertises_no_feed_returns_none() -> None:
    html = '<head><link rel="stylesheet" href="/s.css"><link rel="alternate" hreflang="fi" href="/fi/"></head>'
    assert discover_feed_url(html, BLOG) is None


def test_article_links_drop_navigation_and_the_page_itself() -> None:
    urls = discover_article_urls(_INDEX, BLOG, limit=10)
    assert "https://labs.example.org/blog/2026/10/new-model-card" in urls
    assert "https://labs.example.org/blog/2026/09/safety-framework" in urls
    joined = " ".join(urls)
    for nav in ("/about", "/careers", "https://labs.example.org/ "):
        assert nav not in joined
    assert BLOG.rstrip("/") not in {url.rstrip("/") for url in urls}


def test_article_links_are_bounded_and_deduplicated() -> None:
    html = "".join(
        f'<a href="/blog/2026/10/post-{i}">Post number {i} with a long enough title</a>'
        for i in range(30)
    )
    html += '<a href="/blog/2026/10/post-0">Post number 0 with a long enough title</a>'
    urls = discover_article_urls(html, BLOG, limit=4)
    assert len(urls) == 4
    assert len(set(urls)) == 4


def test_same_host_links_come_before_offsite_ones() -> None:
    html = (
        '<a href="https://elsewhere.example.net/blog/2026/10/offsite-post">An offsite post</a>'
        '<a href="/blog/2026/10/local-post">A local post</a>'
    )
    urls = discover_article_urls(html, BLOG, limit=2)
    assert urls[0].startswith("https://labs.example.org/")


# ---------------------------------------------------------------- collect routes
def test_a_declared_feed_is_collected_without_fetching_children() -> None:
    _FakeRSS.records = [_feed_record()]
    pages = {
        BLOG: '<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head></html>'
    }

    records, warnings = collect_web_source(
        BLOG,
        per_source_limit=10,
        collection_id="ai26",
        transport=_transport(pages),
    )

    assert _FakeRSS.calls == [["https://labs.example.org/feed.xml"]]
    assert [r.source_url for r in records] == ["https://labs.example.org/blog/post"]
    assert warnings == []


def test_dated_article_links_are_collected_when_no_feed_is_declared() -> None:
    pages = {
        BLOG: _INDEX,
        "https://labs.example.org/blog/2026/10/new-model-card": _ARTICLE,
        "https://labs.example.org/blog/2026/09/safety-framework": _ARTICLE_JSONLD,
    }

    records, _ = collect_web_source(
        BLOG,
        per_source_limit=10,
        collection_id="ai26",
        child_limit=5,
        transport=_transport(pages),
        host_validator=_any_host,
    )

    assert len(records) == 2
    assert all(record.source.platform == "web" for record in records)
    assert all(record.source.created_at is not None for record in records)
    assert {str(record.source.created_at)[:10] for record in records} == {
        "2026-10-20",
        "2026-09-30",
    }


def test_undated_children_are_dropped_and_the_snapshot_remains_the_last_resort() -> None:
    undated = "<html><head><title>no date</title></head><body>text</body></html>"
    pages = {
        BLOG: _INDEX,
        "https://labs.example.org/blog/2026/10/new-model-card": undated,
        "https://labs.example.org/blog/2026/09/safety-framework": undated,
    }

    records, _ = collect_web_source(
        BLOG,
        per_source_limit=10,
        collection_id="ai26",
        transport=_transport(pages),
        host_validator=_any_host,
    )

    # A source that publishes nothing datable still records one snapshot: it is the
    # old behaviour, and it is excluded downstream rather than silently dropped here.
    assert len(records) == 1
    assert records[0].source_url == BLOG.rstrip("/") or records[0].source_url == BLOG


def test_verified_fallback_feed_wins_over_discovery() -> None:
    _FakeRSS.records = [_feed_record()]

    records, _ = collect_web_source(
        "https://openai.com/news",
        fallback_feed="https://openai.com/news/rss.xml",
        per_source_limit=10,
        collection_id="ai26",
        transport=_transport({}),
    )

    assert _FakeRSS.calls == [["https://openai.com/news/rss.xml"]]
    assert len(records) == 1


def test_an_unreachable_homepage_raises_a_named_failure() -> None:
    with pytest.raises(WebSourceError) as excinfo:
        collect_web_source(
            BLOG,
            per_source_limit=10,
            collection_id="ai26",
            transport=_transport({}, status={BLOG: 503}),
        )
    assert excinfo.value.reason == "web_fetch_failed"
    assert excinfo.value.status_code == 503


def test_failed_children_do_not_hide_a_reachable_page() -> None:
    pages = {BLOG: _INDEX}
    records, warnings = collect_web_source(
        BLOG,
        per_source_limit=10,
        collection_id="ai26",
        transport=_transport(pages),
        host_validator=_any_host,
    )
    assert len(records) == 1
    assert any(warning.startswith("article_fetch_failures:") for warning in warnings)
