"""Fill the blank `arena` on captured X records from the study's own declared mapping (#336).

The capture-side fix (#345) means new X records are born with their arena. Records captured before
it still carry a blank top-level `arena`, which keeps them out of the paper's stratified sample.
This module is the pure planning half of the backfill: given one stored record and the study
config's account rows, it returns the `$set` payload — or ``None`` when the record is not
attributable, so an unknown handle is counted rather than guessed at.

The I/O half lives in ``scripts/backfill_ai26_arena.py``, which is dry-run by default.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from .attribution import match_account
from .capture_server import capture_meta_for_account

#: Hosts that prove a URL is an X/Twitter page. Anything else is left unattributed.
_X_HOSTS = frozenset(
    {"x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}
)
#: Path segments that are X's own pages, not an account.
_NOT_HANDLES = frozenset(
    {"home", "explore", "search", "i", "settings", "notifications", "messages", "login", "share",
     "intent", "hashtag", "tos", "privacy"}
)


def _blank(value: Any) -> bool:
    return not str(value or "").strip()


def _handle_from_url(url: str) -> str:
    """The account an X/Twitter URL names, or ``""`` when the URL does not name one."""
    parts = urlsplit(str(url or "").strip())
    if parts.netloc.casefold() not in _X_HOSTS:
        return ""
    segments = [segment for segment in parts.path.split("/") if segment]
    if not segments or segments[0].casefold().lstrip("@") in _NOT_HANDLES:
        return ""
    return segments[0].lstrip("@")


def identity(source: Mapping[str, Any]) -> tuple[str, str]:
    """The ``(platform, handle)`` a stored record proves about itself, or ``("", "")``.

    Records captured through the X bridge before #345 carry an empty ``source.platform`` *and* an
    empty ``source.author``; the only surviving identity is the ``source_url`` the bridge wrote.
    Reading it is not a guess — the host and the path decide, and anything ambiguous stays
    unattributed so the audit can count it (#470).
    """
    platform = str(source.get("platform") or "").strip().casefold()
    author = str(source.get("author") or "").strip().lstrip("@")
    from_url = _handle_from_url(str(source.get("source_url") or ""))
    if platform and platform != "x":
        # A declared non-X platform is not repaired from an X-looking URL.
        return platform, author
    if platform == "x":
        return "x", author or from_url
    if not from_url:
        return "", author
    return "x", author or from_url


def plan_update(
    document: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]
) -> dict[str, Any] | None:
    """The fields to write for one stored X record, or ``None`` if it cannot be attributed.

    Matched by ``source.author`` — the handle the capture recorded — against the configured rows
    for ``x``. The top-level ``arena`` is what ``handoff.arena`` and the corpus audit read; the two
    metadata fields are what the analysis layer and child inheritance read. A value already present
    is never overwritten, so re-running is idempotent and a later, better attribution wins.
    """
    source = dict(document.get("source") or {})
    platform, handle = identity(source)
    if platform != "x" or not handle:
        return None
    row = match_account(rows, "x", f"https://x.com/{handle}")
    declared = capture_meta_for_account(row)
    if not declared.get("arena"):
        return None

    metadata = dict(source.get("raw_metadata") or {})
    update: dict[str, Any] = {}
    if _blank(source.get("platform")):
        # The record *is* an X record; the blank field is the capture bug, not a second platform.
        # Only a declared handle reaches this line, so an undeclared one still stays as it is.
        update["source.platform"] = "x"
    if _blank(source.get("author")):
        update["source.author"] = handle
    if _blank(document.get("arena")):
        update["arena"] = declared["arena"]
    if _blank(metadata.get("arena")):
        update["source.raw_metadata.arena"] = declared["arena"]
    if _blank(metadata.get("source_name")) and declared.get("source_name"):
        update["source.raw_metadata.source_name"] = declared["source_name"]
    return update or None
