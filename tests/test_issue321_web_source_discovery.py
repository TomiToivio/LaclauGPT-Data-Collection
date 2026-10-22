"""A `web_source` must yield dated documents, not one undated snapshot (issue #321).

On the browser-free stage the runner gave every `web_source` row one of two fates: if its
homepage happened to be in a hardcoded two-entry fallback map it produced dated articles;
otherwise it stored a single page-level record with no publication time, which the handoff
then excluded. So the elite "blogs and manifestos" layer was 1 analysis-grade record out of
1962 while two individual scholars supplied 525.

These tests pin the discovery step that replaced the map: declared feeds first, then article
links whose pages carry `article:published_time` — and, when neither works, the old
single-snapshot behaviour is retained rather than a record being invented.
"""
from __future__ import annotations

import httpx
import pytest

from laclaugpt_data_collection import ai26_laskin_runner as runner
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord
from laclaugpt_data_collection.web_discovery import discover_article_urls, discover_feed_urls
from laclaugpt_data_collection.web_fetch import WebFetchOutcome, fetch_html_page

FEED_HTML = """
<html><head>
  <link rel="alternate" type="application/rss+xml" title="RSS" href="/feed.xml">
  <link rel="alternate" type="application/rss+xml" title="dupe" href="/feed.xml">
  <link rel="alternate" hreflang="fi" href="/fi/">
</head><body><a href="/blog/post-one">A first post with a headline</a></body></html>
"""

BLOG_HTML = """
<html><body>
  <a href="/blog/first-post-about-ai-safety">A first post about AI safety</a>
  <a href="/blog/second-post-about-compute">A second post about compute</a>
  <a href="/learn/agentic-ai/what-is-agentic-ai">An explainer that is not a post</a>
  <a href="/assets/logo.png">logo</a>
  <a href="/cdn-cgi/l/email-protection#abc">email</a>
  <a href="/printable/pdf">print</a>
  <a href="https://other.example/blog/post">offsite</a>
  <a href="mailto:press@example.com">mail</a>
</body></html>
"""


# --- discovery primitives -------------------------------------------------


def test_declared_feeds_are_found_absolute_and_deduplicated():
    assert discover_feed_urls(FEED_HTML, "https://example.org/news") == [
        "https://example.org/feed.xml"
    ]


def test_only_feed_typed_alternates_count():
    html = '<link rel="alternate" type="text/html" hreflang="fi" href="/fi/">'
    assert discover_feed_urls(html, "https://example.org/") == []


def test_article_candidates_prefer_the_index_section():
    urls = discover_article_urls(BLOG_HTML, "https://example.org/blog/", limit=10)
    # Both /blog/ posts come before the /learn/ explainer that is no less deep.
    assert urls[0].endswith("/blog/first-post-about-ai-safety")
    assert urls[1].endswith("/blog/second-post-about-compute")
    assert urls.index("https://example.org/blog/first-post-about-ai-safety") < urls.index(
        "https://example.org/learn/agentic-ai/what-is-agentic-ai"
    )


def test_article_candidates_exclude_assets_prints_cdn_and_offsite():
    urls = discover_article_urls(BLOG_HTML, "https://example.org/blog/", limit=10)
    joined = " ".join(urls)
    assert "logo.png" not in joined
    assert "cdn-cgi" not in joined
    assert "/printable/" not in joined
    assert "other.example" not in joined
    assert not any(url.startswith("mailto:") for url in urls)


def test_article_candidates_respect_the_limit():
    assert len(discover_article_urls(BLOG_HTML, "https://example.org/blog/", limit=2)) == 2


# --- the fetch used only for discovery ------------------------------------


def _transport(handler):
    return httpx.MockTransport(handler)


def test_fetch_html_page_returns_final_url_and_html():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=FEED_HTML)

    result = fetch_html_page("https://example.org/news", transport=_transport(handler))
    assert result is not None
    final_url, html = result
    assert final_url == "https://example.org/news"
    assert "/feed.xml" in html


def test_fetch_html_page_follows_a_redirect():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/news":
            return httpx.Response(301, headers={"location": "/news/"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text=FEED_HTML)

    result = fetch_html_page("https://example.org/news", transport=_transport(handler))
    assert result is not None and result[0] == "https://example.org/news/".rstrip("/")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, headers={"content-type": "text/html"}, text="missing"),
        httpx.Response(200, headers={"content-type": "application/json"}, text="{}"),
    ],
)
def test_fetch_html_page_returns_none_instead_of_raising(response):
    assert fetch_html_page("https://example.org/x", transport=_transport(lambda request: response)) is None


# --- the runner's web_source branch --------------------------------------


def _record(url: str, *, published: str | None) -> NormalizedRecord:
    record = NormalizedRecord(
        document_id=url,
        platform="web",
        source_url=url,
        text="Article body",
        raw_payload={"id": url},
        collection_provenance=CollectionProvenance(module="issue-321-test"),
    )
    record.source.created_at = published
    return record


def _job(**overrides) -> dict:
    row = {
        "kind": "web_source",
        "name": "example_blog",
        "homepage": "https://example.org/blog/",
        "arena": "elites",
        "priority": "P1",
        "source_family": "frontier lab",
    }
    row.update(overrides)
    return row


def test_a_declared_feed_is_collected_as_dated_articles(monkeypatch):
    seen: dict = {}

    class FakeRSS:
        def __init__(self, feed_urls, max_items_per_feed=0):
            seen["feeds"] = list(feed_urls)
            seen["limit"] = max_items_per_feed

        def collect(self):
            class Result:
                records = [
                    _record("https://example.org/blog/post-one", published="2026-10-20T10:00:00Z"),
                    _record("https://example.org/blog/undated", published=None),
                ]
                warnings: list[str] = []

            return Result()

    monkeypatch.setattr(runner, "fetch_html_page", lambda url, **kw: ("https://example.org/blog/", FEED_HTML))
    monkeypatch.setattr(runner, "RSSCollector", FakeRSS)

    records, warnings = runner._records_for_job(
        _job(), collection_id="ai26", worker_id="test", per_source_limit=3
    )

    assert seen["feeds"] == ["https://example.org/feed.xml"]  # root-absolute href in the fixture
    assert seen["limit"] == 3
    # Only the dated article survives: an undated one would be excluded downstream anyway.
    assert [record.source_url for record in records] == ["https://example.org/blog/post-one"]
    assert records[0].source.raw_metadata["source_name"] == "example_blog"
    assert warnings == []


def test_article_links_are_followed_and_undated_children_dropped(monkeypatch):
    fetched: list[str] = []

    def fake_child(url, parent, **kwargs):
        fetched.append(url)
        published = "2026-10-19T08:00:00Z" if "first-post" in url else None
        return WebFetchOutcome(url, _record(url, published=published))

    monkeypatch.setattr(runner, "fetch_html_page", lambda url, **kw: ("https://example.org/blog/", BLOG_HTML))
    monkeypatch.setattr(runner, "fetch_web_child", fake_child)

    records, _ = runner._records_for_job(
        _job(), collection_id="ai26", worker_id="test", per_source_limit=4
    )

    assert len(fetched) <= 4
    assert [record.source_url for record in records] == [
        "https://example.org/blog/first-post-about-ai-safety"
    ]


def test_without_discovery_the_single_snapshot_behaviour_is_kept(monkeypatch):
    """No feed, no dated child: the old path, which the handoff excludes, still runs."""
    snapshot = _record("https://example.org/blog/", published=None)

    monkeypatch.setattr(runner, "fetch_html_page", lambda url, **kw: None)
    monkeypatch.setattr(runner, "fetch_web_child", lambda url, parent, **kw: WebFetchOutcome(url, snapshot))

    records, _ = runner._records_for_job(
        _job(), collection_id="ai26", worker_id="test", per_source_limit=4
    )
    # canonicalize_source_url drops the trailing slash; the path is the identity.
    assert [record.source_url for record in records] == ["https://example.org/blog"]
    assert records[0].source.created_at is None
