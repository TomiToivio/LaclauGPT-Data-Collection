"""Safe external-link fetching for canonical WEB child records.

The fetcher is deliberately small and synchronous. Callers invoke it only after the
originating record is durably stored. Failures are returned as data and never invalidate
the parent record.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx

from .models import (
    CanonicalRecord,
    CollectionProvenance,
    ContentSection,
    MediaReference,
    RawCaptureSection,
    SourceSection,
    canonicalize_source_url,
)
from .realtime import extract_external_urls

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
#: Publication time in the shapes public pages actually use. The OpenGraph/meta
#: form is the one most blogs emit; JSON-LD is what Next.js and most CMS themes emit
#: instead, and a bare <time datetime> is common on hand-built sites. Reading only
#: the first form made #321's article route yield undated children -- which the
#: handoff then excludes -- on exactly those pages.
_PUBLISHED_PATTERNS = (
    re.compile(r"(?:article:published_time|datePublished)[^>]+content=[\"']([^\"']+)", re.I),
    re.compile(r"\"datePublished\"\s*:\s*\"([^\"]+)\"", re.I),
    re.compile(r"<time[^>]+datetime=[\"']([^\"']+)[\"']", re.I),
)
_ALLOWED_TYPES = (
    "text/html",
    "text/plain",
    "application/pdf",
    "application/xml",
    "text/xml",
    "application/xhtml+xml",
)


@dataclass(frozen=True)
class WebFetchOutcome:
    url: str
    record: CanonicalRecord | None
    error: str = ""
    status_code: int | None = None



#: Compression signatures a `text/*` body should never start with. If one appears the origin (or a
#: cache in front of it) served compressed bytes under a text label, or httpx could not decode the
#: `content-encoding`; either way the bytes are not text yet.
_MAGIC_ENCODINGS = (
    (b"\x1f\x8b", "gzip"),
    (b"\x28\xb5\x2f\xfd", "zstd"),
    (b"\x78\x01", "zlib"),
    (b"\x78\x9c", "zlib"),
    (b"\x78\xda", "zlib"),
)

#: A decoded body is refused as text when it is this broken. Measured against the AI26 store: the one
#: bad record is 43.8 % U+FFFD and carries 896 control characters, while legitimate Finnish and
#: Japanese pages contain neither — so these thresholds separate the two without touching a script.
MAX_REPLACEMENT_SHARE = 0.10
MAX_CONTROL_CHARS = 5


def _looks_compressed(body: bytes) -> str:
    """The compression the body starts with, or an empty string."""
    for magic, name in _MAGIC_ENCODINGS:
        if body.startswith(magic):
            return name
    return ""


def _decompress(body: bytes, kind: str) -> bytes | None:
    """Undo a compression layer, or None when it cannot be undone here."""
    try:
        if kind == "gzip":
            import gzip

            return gzip.decompress(body)
        if kind == "zlib":
            import zlib

            return zlib.decompress(body)
        if kind == "zstd":
            import zstandard  # optional dependency

            return zstandard.ZstdDecompressor().decompress(body)
    except Exception:  # noqa: BLE001 - an undecodable body is a rejection, not a crash
        return None
    return None


def decode_text_body(body: bytes, encoding: str | None = None) -> tuple[str, dict[str, object]]:
    """Decode a fetched body as text, and say how trustworthy the result is.

    ``errors="replace"`` is kept — refusing to decode would lose the legitimate-but-imperfect pages —
    but the count is returned so the caller can refuse the ones that are not text at all. Without this,
    a compressed body becomes a valid ``str`` full of U+FFFD, the record is stored as ``ready``, and
    the analysis stage codes mojibake as discourse (issue #429).
    """
    diagnostics: dict[str, object] = {"byte_size": len(body), "decompressed_from": ""}
    compressed = _looks_compressed(body)
    if compressed:
        expanded = _decompress(body, compressed)
        diagnostics["compressed_as"] = compressed
        if expanded is not None:
            body = expanded
            diagnostics["decompressed_from"] = compressed
            diagnostics["decoded_byte_size"] = len(expanded)
    text = body.decode(encoding or "utf-8", errors="replace")
    replacements = text.count("\ufffd")
    control = sum(1 for character in text
                  if (ord(character) < 32 and character not in "\n\r\t") or ord(character) == 127)
    diagnostics.update({
        "characters": len(text),
        "replacement_characters": replacements,
        "replacement_share": round(replacements / len(text), 4) if text else 0.0,
        "control_characters": control,
    })
    return text, diagnostics


def text_is_plausible(diagnostics: dict[str, object]) -> tuple[bool, str]:
    """Whether a decoded body may be stored as text, with the reason when it may not."""
    share = float(diagnostics.get("replacement_share") or 0.0)
    control = int(diagnostics.get("control_characters") or 0)
    if share > MAX_REPLACEMENT_SHARE:
        return False, (f"replacement_share={share:.3f} exceeds {MAX_REPLACEMENT_SHARE:.2f} "
                       f"({diagnostics.get('replacement_characters')} of "
                       f"{diagnostics.get('characters')} characters)")
    if control > MAX_CONTROL_CHARS:
        return False, f"control_characters={control} exceeds {MAX_CONTROL_CHARS}"
    return True, ""

def external_urls_for_record(record: CanonicalRecord) -> list[str]:
    """Return preserved expanded links plus links visible in normalized text."""
    candidates = list(record.source.raw_metadata.get("external_urls") or [])
    candidates.extend(extract_external_urls(record.content.text, originating_url=record.source_url))
    found: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        canonical = canonicalize_source_url(str(value))
        if canonical and canonical not in seen:
            seen.add(canonical)
            found.append(canonical)
    return found


def _public_host(url: str) -> bool:
    """Reject localhost/private/link-local targets before each HTTP request."""
    host = urlsplit(url).hostname
    if not host or host.lower() in {"localhost", "localhost.localdomain"}:
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    if not addresses:
        return False
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def _html_text(value: str) -> str:
    text = _TAG_RE.sub(" ", value)
    return " ".join(unescape(text).split())


def _title(value: str) -> str | None:
    match = _TITLE_RE.search(value)
    return _html_text(match.group(1))[:500] if match else None


def _published(value: str) -> str | None:
    for pattern in _PUBLISHED_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group(1).strip()
    return None


def fetch_html_page(
    url: str,
    *,
    timeout_seconds: float = 20.0,
    max_bytes: int = 5_000_000,
    transport: httpx.BaseTransport | None = None,
    host_validator: Callable[[str], bool] = _public_host,
) -> tuple[str, str] | None:
    """Fetch a page for *discovery* only: ``(final_url, html)`` or ``None``.

    This produces no record on purpose. It exists so the stage can learn which
    documents a ``web_source`` homepage publishes (#321), and it deliberately shares
    the same host validation and size limits as :func:`fetch_web_child` so discovery
    cannot reach anywhere the fetcher could not.
    """
    current = canonicalize_source_url(url)
    if urlsplit(current).scheme not in {"http", "https"}:
        return None
    try:
        with httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": "LaclauGPT-Data-Collection/0.1 research fetcher"},
        ) as client:
            requested = current
            seen: set[str] = set()
            for _ in range(5):
                if requested in seen or not host_validator(requested):
                    return None
                seen.add(requested)
                response = client.get(requested)
                location = response.headers.get("location")
                if response.status_code in {301, 302, 303, 307, 308} and location:
                    requested = urljoin(requested, location)
                    current = canonicalize_source_url(requested)
                    continue
                if response.status_code >= 400:
                    return None
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if "html" not in content_type:
                    return None
                body = response.content[: max_bytes + 1]
                if len(body) > max_bytes:
                    return None
                candidate, diagnostics = decode_text_body(body, response.encoding)
                plausible, _ = text_is_plausible(diagnostics)
                return (current, candidate) if plausible else None
    except Exception:  # noqa: BLE001 - discovery must never fail collection
        return None
    return None


def fetch_web_child(
    url: str,
    parent: CanonicalRecord,
    *,
    collection_id: str = "ai26",
    arena: str = "",
    timeout_seconds: float = 20.0,
    max_bytes: int = 5_000_000,
    transport: httpx.BaseTransport | None = None,
    host_validator: Callable[[str], bool] = _public_host,
) -> WebFetchOutcome:
    """Fetch one public HTTP(S) target and map it to a canonical WEB child record."""
    current = canonicalize_source_url(url)
    if urlsplit(current).scheme not in {"http", "https"}:
        return WebFetchOutcome(current, None, "unsupported_scheme")

    try:
        with httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": "LaclauGPT-Data-Collection/0.1 research fetcher"},
        ) as client:
            response = None
            original = current
            seen: set[str] = set()
            # `requested` is the exact URL handed to the server for the current
            # hop; `current` is its canonical form, used only as the record
            # identity. The two are tracked separately on purpose: the canonical
            # form strips a trailing slash, so requesting the canonical URL and
            # then comparing canonical forms makes a site that redirects
            # "/blog" -> "/blog/" look like an unbreakable loop. The loop guard
            # therefore keys on the raw requested URL, and redirects are followed
            # from the server's raw Location (#205).
            requested = current
            for _ in range(5):
                if requested in seen:
                    return WebFetchOutcome(current, None, "redirect_loop")
                seen.add(requested)
                if not host_validator(requested):
                    return WebFetchOutcome(current, None, "unsafe_or_unresolvable_host")
                response = client.get(requested)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        return WebFetchOutcome(current, None, "redirect_without_location")
                    requested = urljoin(requested, location)
                    current = canonicalize_source_url(requested)
                    continue
                break
            if response is None:
                return WebFetchOutcome(current, None, "no_response")
            response.raise_for_status()
            content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].lower()
            if not any(content_type.startswith(value) for value in _ALLOWED_TYPES):
                return WebFetchOutcome(current, None, f"unsupported_content_type:{content_type}")
            body = response.content[: max_bytes + 1]
            if len(body) > max_bytes:
                return WebFetchOutcome(current, None, "response_too_large")
    except httpx.HTTPStatusError as exc:
        return WebFetchOutcome(current, None, "http_error", exc.response.status_code)
    except Exception as exc:  # noqa: BLE001
        return WebFetchOutcome(current, None, str(exc)[:300])

    text = ""
    title = None
    published_at = None
    body_metadata: dict[str, object] = {}
    media: list[MediaReference] = []
    if content_type == "application/pdf":
        media.append(MediaReference(kind="pdf", url=current, media_index=0))
    else:
        decoded, body_diagnostics = decode_text_body(body, response.encoding)
        plausible, refusal = text_is_plausible(body_diagnostics)
        if not plausible:
            # Store the refusal, not the mojibake: the row is visibly absent with a reason, instead of
            # present with prose that is really compressed bytes (#429).
            return WebFetchOutcome(
                current, None,
                f"binary_body_rejected:{refusal}",
            )
        if "html" in content_type:
            title = _title(decoded)
            published_at = _published(decoded)
            text = _html_text(decoded)[:200_000]
        else:
            text = decoded[:200_000]
        body_metadata = body_diagnostics

    fetched_at = datetime.now(UTC).isoformat()
    source = SourceSection(
        platform="web",
        source_type="WEB",
        created_at=published_at,
        collected_at=fetched_at,
        collector="external-link-fetcher",
        collection_method="http",
        parent_source_url=parent.source_url,
        raw_metadata={
            "collection_id": collection_id,
            "arena": arena,
            "discovered_via": parent.source_url,
            "original_link": original,
            "final_url": current,
            "http_content_type": content_type,
        },
    )
    child = CanonicalRecord(
        source_url=current,
        raw_capture=RawCaptureSection(
            payload=None,
            content_type=content_type,
            captured_at=fetched_at,
            metadata={"byte_size": len(body), "body_not_inlined": True,
                      "text_decode": body_metadata},
        ),
        source=source,
        content=ContentSection(text=text, title=title, media_references=media),
        provenance=[
            CollectionProvenance(
                module="external-link-fetcher",
                captured_at=fetched_at,
                visited_url=original,
                transformations=["follow-safe-redirects", "fetch-web-child"],
                metadata={
                    "collection_id": collection_id,
                    "arena": arena,
                    "parent_source_url": parent.source_url,
                },
            )
        ],
    )
    child.refresh_human_readable()
    return WebFetchOutcome(current, child)
