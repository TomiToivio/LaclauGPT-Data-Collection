"""Feed and article discovery for browser-free ``web_source`` rows (#321).

A configured ``web_source`` used to contribute at most one undated homepage
snapshot. The handoff excludes anything without a publication time, so the elite
"blogs and manifestos" layer was structurally absent from the analysis corpus:
1 analysis-grade web document out of 1 962, with two scholars' social posts
supplying 525.

Two routes turn one homepage into dated documents, cheapest first:

1. **Declared feed.** The page advertises ``<link rel="alternate"
   type="application/rss+xml">``; collect that feed, which yields dated articles.
   This generalises the hardcoded two-entry fallback map instead of extending it
   one URL at a time.
2. **Article links.** No feed means the page's own links are the index: fetch a
   bounded number of them as children and keep the ones that carry a publication
   time (``article:published_time``, ``datePublished``, ``<time datetime>``).

Both routes are bounded and polite: one homepage fetch, at most one feed, and at
most ``child_limit`` article fetches per source per cycle, all through the same
host validation the external-link fetcher uses.
"""
from __future__ import annotations

import re
from html import unescape
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

import httpx

from .collectors.rss import RSSCollector
from .models import CollectionProvenance, NormalizedRecord
from .web_fetch import fetch_web_child

USER_AGENT = "LaclauGPT-Data-Collection/0.1 research fetcher"

_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.I)
_ANCHOR_RE = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_ATTR_RE = re.compile(r"([a-zA-Z:-]+)\s*=\s*[\"']([^\"']*)[\"']")
_TAG_RE = re.compile(r"<[^>]+>")
#: Paths that are navigation furniture, never articles.
_NAV_SEGMENTS = {
    "about",
    "contact",
    "privacy",
    "privacy-policy",
    "terms",
    "legal",
    "login",
    "signin",
    "sign-in",
    "signup",
    "subscribe",
    "careers",
    "jobs",
    "press-kit",
    "cookie-policy",
    "imprint",
}
#: A last path segment that reads like an article: a slug, a date part or an id.
_ARTICLE_SLUG_RE = re.compile(r"[a-z0-9]+[-_][a-z0-9-]+|\d{4}|\d{2,}", re.I)


class WebSourceError(RuntimeError):
    """A configured ``web_source`` could not be read at all."""

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


def discover_feed_url(html: str, base_url: str) -> str | None:
    """The feed a page advertises, resolved against it. ``None`` when it advertises none."""
    for tag in _LINK_TAG_RE.findall(html or ""):
        attributes = {name.lower(): value for name, value in _ATTR_RE.findall(tag)}
        rels = set(attributes.get("rel", "").lower().split())
        content_type = attributes.get("type", "").lower()
        if "alternate" not in rels or not content_type.startswith(("application/rss", "application/atom")):
            continue
        href = attributes.get("href", "").strip()
        if not href:
            continue
        resolved = urljoin(base_url, unescape(href))
        if urlsplit(resolved).scheme in {"http", "https"}:
            return resolved
    return None


def discover_article_urls(html: str, base_url: str, *, limit: int) -> list[str]:
    """Article-looking links on a page, same host first, de-duplicated, bounded.

    Heuristics, deliberately conservative: a link that points back at the page
    itself, to a navigation path, or to another host with no article-shaped path is
    dropped. Order is preserved so a page's own prominence survives.
    """
    if limit <= 0:
        return []
    base = _identity(base_url)
    seen: set[str] = set()
    same_host: list[str] = []
    other_host: list[str] = []
    for href, anchor_text in _ANCHOR_RE.findall(html or ""):
        href = unescape(href).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        resolved = urljoin(base_url, href)
        parts = urlsplit(resolved)
        if parts.scheme not in {"http", "https"}:
            continue
        identity = _identity(resolved)
        if identity == base or identity in seen:
            continue
        last_segment = parts.path.rstrip("/").rsplit("/", 1)[-1]
        if not last_segment or last_segment.lower() in _NAV_SEGMENTS:
            continue
        text = _TAG_RE.sub("", anchor_text).strip()
        looks_like_article = bool(_ARTICLE_SLUG_RE.search(last_segment)) or len(text) >= 25
        if not looks_like_article:
            continue
        seen.add(identity)
        target = same_host if _host(parts) == _host(urlsplit(base_url)) else other_host
        target.append(resolved)
    return (same_host + other_host)[:limit]


def _fetch(
    url: str,
    parent: Any,
    *,
    collection_id: str,
    arena: str,
    timeout_seconds: float,
    transport: httpx.BaseTransport | None,
    host_validator: Callable[[str], bool] | None,
):  # noqa: ANN201 - WebFetchOutcome, kept untyped to stay import-light
    # Only pass what was actually chosen: a caller (or a test) that wraps this
    # fetcher must not meet ``transport=None`` twice in its own signature.
    optional = {
        name: value
        for name, value in (("transport", transport), ("host_validator", host_validator))
        if value is not None
    }
    return fetch_web_child(
        url,
        parent,
        collection_id=collection_id,
        arena=arena,
        timeout_seconds=timeout_seconds,
        **optional,
    )


def collect_web_source(
    url: str,
    *,
    fallback_feed: str | None = None,
    per_source_limit: int,
    collection_id: str,
    arena: str = "",
    child_limit: int = 5,
    timeout_seconds: float = 20.0,
    transport: httpx.BaseTransport | None = None,
    host_validator: Callable[[str], bool] | None = None,
) -> tuple[list[Any], list[str]]:
    """Dated documents for one configured ``web_source``, plus diagnostics.

    Feed rows are ``NormalizedRecord``s, fetched article children are
    ``CanonicalRecord``s; the runner stamps both the same way.

    Order: verified fallback feed → feed the page advertises → article links that
    carry a publication time → the single homepage snapshot as a last resort, so a
    reachable source is still recorded even when it publishes nothing datable.
    """
    if fallback_feed:
        result = RSSCollector([fallback_feed], max_items_per_feed=per_source_limit).collect()
        return list(result.records), list(result.warnings)

    html = _fetch_html(url, timeout_seconds=timeout_seconds, transport=transport)

    discovered = discover_feed_url(html, url)
    if discovered:
        result = RSSCollector([discovered], max_items_per_feed=per_source_limit).collect()
        records = list(result.records)
        warnings = list(result.warnings)
        if records:
            return records, warnings
        if warnings:
            # A feed that advertises itself but serves nothing is worth reporting,
            # then the article route still gets its chance.
            warnings = [f"advertised_feed_empty:{discovered}", *warnings]
        else:
            warnings = [f"advertised_feed_empty:{discovered}"]

    parent = NormalizedRecord(
        document_id=url,
        platform="web",
        source_url=url,
        text="",
        raw_payload={},
        collection_provenance=CollectionProvenance(module="ai26-laskin-web-seed"),
    )
    dated: list[NormalizedRecord] = []
    failures = 0
    for article_url in discover_article_urls(html, url, limit=child_limit):
        outcome = _fetch(
            article_url,
            parent,
            collection_id=collection_id,
            arena=arena,
            timeout_seconds=timeout_seconds,
            transport=transport,
            host_validator=host_validator,
        )
        if outcome.record is None:
            failures += 1
            continue
        if outcome.record.source.created_at is None:
            continue
        dated.append(outcome.record)
    if dated:
        warnings = list(warnings) if discovered else []
        return dated, warnings

    homepage = _fetch(
        url,
        parent,
        collection_id=collection_id,
        arena=arena,
        timeout_seconds=timeout_seconds,
        transport=transport,
        host_validator=host_validator,
    )
    if homepage.record is None:
        raise WebSourceError("web_fetch_failed", status_code=homepage.status_code)
    notes = list(warnings) if discovered else []
    if failures:
        notes.append(f"article_fetch_failures:{failures}")
    return [homepage.record], notes


def _fetch_html(
    url: str,
    *,
    timeout_seconds: float,
    transport: httpx.BaseTransport | None,
) -> str:
    try:
        with httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            if "html" not in response.headers.get("content-type", "").lower():
                return ""
            return response.text[: 2_000_000]
    except httpx.HTTPStatusError as exc:
        raise WebSourceError("web_fetch_failed", status_code=exc.response.status_code) from exc
    except Exception as exc:  # noqa: BLE001
        raise WebSourceError(str(exc)[:200] or "web_fetch_failed") from exc


def _identity(url: str) -> str:
    """Dedupe key: scheme-less, ``www.``-less, fragment- and trailing-slash-free."""
    parts = urlsplit(url)
    host = _host(parts)
    path = parts.path.rstrip("/") or "/"
    return f"{host}{path}"


def _host(parts: object) -> str:
    host = getattr(parts, "netloc", "").lower()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    return host[4:] if host.startswith("www.") else host


