"""Discover how a `web_source` homepage publishes dated documents.

A `web_source` row gives the stage a homepage, not a feed. On the browser-free stage
the runner used to fetch that page once, store one undated snapshot, and let the
handoff exclude it — so the elite "blogs and manifestos" layer never reached the
analysis corpus (#321). The pages themselves are fine; what was missing was the step
that turns "a homepage" into "a list of documents".

Two routes, in the order the issue asks for them:

1. **Declared feeds.** Most first-party blogs advertise their feed in the head with
   ``<link rel="alternate" type="application/rss+xml" href="...">``. Following it
   yields dated articles with no per-site knowledge, which is why the hardcoded
   two-entry fallback map was the wrong shape: it only scaled by hand.
2. **Article links with publication times.** Where no feed is declared, the index
   page still links to articles, and those article pages usually carry
   ``article:published_time`` / ``datePublished`` (already parsed by
   ``web_fetch.fetch_web_child``). So the discovery step only has to propose
   candidates and the existing fetcher supplies the date.

This module deliberately uses the standard library only — a head scan and an anchor
scan do not justify a parser dependency, and it keeps the stage importable on the
minimal runtime.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

# Extensions that are never article pages, and path segments that are navigation.
_ASSET_RE = re.compile(
    r"\.(?:png|jpe?g|gif|svg|webp|avif|ico|css|js|mjs|json|xml|rss|atom|pdf|zip|gz|mp4|mp3|woff2?)$",
    re.I,
)
# Paths that are never a document: CDN protection shims (Cloudflare rewrites mailto
# links into /cdn-cgi/l/email-protection...), print/AMP variants and asset folders.
_NON_DOCUMENT_RE = re.compile(r"/(?:cdn-cgi|cdn|assets?|static|media|print(?:able)?|amp)/", re.I)

_NAV_SEGMENTS = {
    "about", "contact", "careers", "jobs", "pricing", "login", "signin", "signup",
    "privacy", "terms", "legal", "cookies", "search", "tag", "tags", "category",
    "categories", "author", "authors", "page", "feed", "rss", "sitemap", "newsletter",
}

_FEED_TYPES = {"application/rss+xml", "application/atom+xml", "application/feed+json"}


class _HeadScan(HTMLParser):
    """Collects declared feeds and anchors in one pass."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.feeds: list[str] = []
        self.anchors: list[tuple[str, str]] = []  # (href, anchor text)
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): (value or "") for name, value in attrs}
        if tag == "link":
            rel = values.get("rel", "").lower().split()
            kind = values.get("type", "").lower().split(";")[0].strip()
            href = values.get("href", "").strip()
            if "alternate" in rel and kind in _FEED_TYPES and href:
                self.feeds.append(href)
        elif tag == "a":
            self._current_href = values.get("href", "").strip()
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_href is not None:
            text = " ".join("".join(self._current_text).split())
            self.anchors.append((self._current_href, text))
            self._current_href = None
            self._current_text = []


def _scan(html: str) -> _HeadScan:
    parser = _HeadScan()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed markup must not fail collection
        pass
    return parser


def discover_feed_urls(html: str, base_url: str) -> list[str]:
    """Feed URLs the page declares, absolute and de-duplicated, in document order."""
    found: list[str] = []
    for href in _scan(html).feeds:
        absolute = urljoin(base_url, href)
        if urlsplit(absolute).scheme in {"http", "https"} and absolute not in found:
            found.append(absolute)
    return found


def _looks_like_article(href: str, base_url: str) -> bool:
    parts = urlsplit(urljoin(base_url, href))
    if parts.scheme not in {"http", "https"}:
        return False
    if parts.netloc and parts.netloc != urlsplit(base_url).netloc:
        return False
    path = parts.path
    if not path or path == "/" or _ASSET_RE.search(path) or _NON_DOCUMENT_RE.search(path):
        return False
    segments = [segment for segment in path.strip("/").split("/") if segment]
    if not segments:
        return False
    if any(segment.lower() in _NAV_SEGMENTS for segment in segments[:-1]):
        return False
    # An article URL has some path under the index, not just "/about".
    return len(segments) >= 2 or bool(parts.query) or len(segments[-1]) > 12


def discover_article_urls(html: str, base_url: str, *, limit: int = 10) -> list[str]:
    """Candidate article URLs linked from an index page, best-first and de-duplicated.

    Ranking is deliberately crude and explainable, in this order:

    1. links inside the index page's own section (``/blog/`` index -> ``/blog/slug``
       first, so an ``ai.meta.com/blog/`` index prefers its posts over ``/learn/``
       explainers that happen to be deeper);
    2. deeper paths before shallower ones;
    3. anchors whose text is long enough to be a headline.

    The caller still keeps only pages that carry a publication time, so a wrong guess
    costs one fetch, never a wrong record.
    """
    index_path = urlsplit(base_url).path.strip("/")
    index_section = index_path.split("/")[0].lower() if index_path else ""
    candidates: list[tuple[int, int, int, str]] = []
    seen: set[str] = set()
    for position, (href, text) in enumerate(_scan(html).anchors):
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        if absolute in seen or not _looks_like_article(absolute, base_url):
            continue
        seen.add(absolute)
        segments = [s for s in urlsplit(absolute).path.strip("/").split("/") if s]
        same_section = bool(index_section) and segments[0].lower() == index_section
        candidates.append(
            (
                0 if same_section else 1,
                -len(segments),
                -min(len(text), 120),
                absolute,
            )
        )
    candidates.sort()
    return [url for _, _, _, url in candidates[:limit]]
