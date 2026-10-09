from __future__ import annotations

import httpx

from laclaugpt_data_collection.models import (
    CanonicalRecord,
    ContentSection,
    SourceSection,
)
from laclaugpt_data_collection.normalize import normalise
from laclaugpt_data_collection.web_fetch import external_urls_for_record, fetch_web_child


def _parent() -> CanonicalRecord:
    return CanonicalRecord(
        source_url="https://x.com/example/status/1",
        source=SourceSection(
            platform="x",
            source_type="post",
            created_at="2026-09-16T10:00:00Z",
            raw_metadata={"external_urls": ["https://example.org/article?utm_source=x"]},
        ),
        content=ContentSection(text="See https://example.org/article?utm_source=x"),
    )


def test_normalise_preserves_expanded_x_urls() -> None:
    record = normalise(
        "x",
        {
            "id": "123",
            "link": "https://x.com/example/status/123",
            "timestamp": "2026-09-16T10:00:00Z",
            "body": "source",
            "urls": "https://example.org/a,https://example.org/b",
        },
    )
    assert record.source.raw_metadata["external_urls"] == [
        "https://example.org/a",
        "https://example.org/b",
    ]


def test_external_urls_are_deduplicated_and_canonicalized() -> None:
    assert external_urls_for_record(_parent()) == ["https://example.org/article"]


def test_html_fetch_creates_web_child_with_parent_provenance() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://example.org/article")
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=(
                '<html><head><title>AI policy</title>'
                '<meta property="article:published_time" content="2026-09-15T12:00:00Z">'
                '</head><body><h1>AI policy</h1><p>Substantive source text.</p></body></html>'
            ),
        )

    outcome = fetch_web_child(
        "https://example.org/article",
        _parent(),
        collection_id="ai26",
        arena="elites",
        transport=httpx.MockTransport(handler),
        host_validator=lambda _url: True,
    )
    assert outcome.error == ""
    assert outcome.record is not None
    child = outcome.record
    assert child.source_url == "https://example.org/article"
    assert child.source.source_type == "WEB"
    assert child.source.parent_source_url == "https://x.com/example/status/1"
    assert child.source.created_at == "2026-09-15T12:00:00Z"
    assert child.source.raw_metadata["collection_id"] == "ai26"
    assert child.source.raw_metadata["arena"] == "elites"
    assert child.content.title == "AI policy"
    assert "Substantive source text" in child.content.text


def test_pdf_fetch_creates_first_class_document_reference() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-test")

    outcome = fetch_web_child(
        "https://example.org/paper.pdf",
        _parent(),
        transport=httpx.MockTransport(handler),
        host_validator=lambda _url: True,
    )
    assert outcome.record is not None
    refs = outcome.record.content.media_references
    assert len(refs) == 1
    assert refs[0].kind == "pdf"
    assert refs[0].url == "https://example.org/paper.pdf"


def test_failed_fetch_returns_error_without_mutating_parent() -> None:
    parent = _parent()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    outcome = fetch_web_child(
        "https://example.org/down",
        parent,
        transport=httpx.MockTransport(handler),
        host_validator=lambda _url: True,
    )
    assert outcome.record is None
    assert outcome.error
    assert parent.source_url == "https://x.com/example/status/1"


def test_trailing_slash_redirect_is_followed_not_a_loop() -> None:
    """A site that redirects "/blog" -> "/blog/" must be followed, not treated
    as a loop (#205). Redirects are followed from the server's raw Location and
    only the final URL is canonicalized, so the trailing-slash hop resolves."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/blog":
            return httpx.Response(301, headers={"location": "/blog/"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><title>Blog</title><body>ok</body></html>",
        )

    outcome = fetch_web_child(
        "https://example.org/blog/",
        _parent(),
        transport=httpx.MockTransport(handler),
        host_validator=lambda _url: True,
    )
    assert outcome.error == ""
    assert outcome.record is not None
    # The seed canonicalizes to /blog; the server redirects to /blog/ which is a
    # 200, and the final canonical record identity is /blog again.
    assert outcome.record.source_url == "https://example.org/blog"
    assert calls == ["https://example.org/blog", "https://example.org/blog/"]


def test_genuine_redirect_loop_is_still_detected() -> None:
    """A real self-referential loop (raw URL A -> raw URL B -> raw URL A) is
    still caught rather than fetched forever."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/a":
            return httpx.Response(301, headers={"location": "/b"})
        return httpx.Response(301, headers={"location": "/a"})

    outcome = fetch_web_child(
        "https://example.org/a",
        _parent(),
        transport=httpx.MockTransport(handler),
        host_validator=lambda _url: True,
    )
    assert outcome.record is None
    assert outcome.error == "redirect_loop"
    assert calls == ["https://example.org/a", "https://example.org/b"]

