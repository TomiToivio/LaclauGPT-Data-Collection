"""Discover dated first-party articles and RSS feeds from configured web landing pages.

No browser or JavaScript execution. Bound every index and child fetch, and never
claim that an undated landing page is an analysis-grade article.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from .web_fetch import _public_host


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.articles: list[str] = []
        self.feeds: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        href = data.get("href")
        if not href:
            return
        if tag == "link" and "alternate" in (data.get("rel") or "").lower():
            if any(t in (data.get("type") or "").lower() for t in ("rss+xml", "atom+xml")):
                self.feeds.append(href)
        if tag == "a":
            self.articles.append(href)


def discover_web_links(url: str, *, limit: int = 5) -> tuple[list[str], list[str]]:
    """Return same-host candidate article URLs and advertised feed URLs.

    The index is bounded and SSRF-checked. Child requests undergo the separate
    safe redirect/host checks in fetch_web_child.
    """
    if not _public_host(url):
        raise ValueError("unsafe_web_source_url")
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        response = client.get(url, headers={"User-Agent": "LaclauGPT-Data-Collection/0.1"})
        response.raise_for_status()
        if not response.headers.get("content-type", "").lower().startswith(("text/html", "application/xhtml+xml")):
            return [], []
        if len(response.content) > 2_000_000:
            raise ValueError("web_source_index_too_large")
        parsed = _Links()
        parsed.feed(response.text)
    host = urlsplit(url).hostname
    def safe_link(href: str) -> str | None:
        absolute = urljoin(url, href)
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https") or parts.hostname != host:
            return None
        if parts.username or parts.password:
            return None
        return absolute.split("#", 1)[0]

    def unique(items: list[str]) -> list[str]:
        seen: set[str] = set()
        output: list[str] = []
        for href in items:
            link = safe_link(href)
            if link and link.rstrip("/") != url.rstrip("/") and link not in seen:
                seen.add(link)
                output.append(link)
        return output

    # Landing-page navigation should not consume the whole fetch budget. The
    # publication-time check below is the authority on whether a link is evidence.
    return unique(parsed.feeds)[:3], unique(parsed.articles)[:max(limit * 8, 16)]
