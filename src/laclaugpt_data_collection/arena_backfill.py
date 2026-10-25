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

from .attribution import match_account
from .capture_server import capture_meta_for_account


def _blank(value: Any) -> bool:
    return not str(value or "").strip()


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
    if str(source.get("platform") or "").casefold() != "x":
        return None
    handle = str(source.get("author") or "").strip().lstrip("@")
    if not handle:
        return None
    row = match_account(rows, "x", f"https://x.com/{handle}")
    declared = capture_meta_for_account(row)
    if not declared.get("arena"):
        return None

    metadata = dict(source.get("raw_metadata") or {})
    update: dict[str, Any] = {}
    if _blank(document.get("arena")):
        update["arena"] = declared["arena"]
    if _blank(metadata.get("arena")):
        update["source.raw_metadata.arena"] = declared["arena"]
    if _blank(metadata.get("source_name")) and declared.get("source_name"):
        update["source.raw_metadata.source_name"] = declared["source_name"]
    return update or None
