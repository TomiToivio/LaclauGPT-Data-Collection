"""Work out which configured source a captured page belongs to (issue #336).

The browser captures a *page*: the study config knows which handles belong to which group, and a
group carries the arena the study publishes. That relation was used to build the tour URL list and
then dropped — the records the capture returned had no `arena` and no `source.name`, so 40% of the
analysis-grade corpus lost the actor→arena mapping at the moment of capture, and external-link
children inherited the blank.

This module is the one place that answers "which configured row is this page?" so the capture
server, the record normaliser and any backfill all give the same answer. It never invents an
attribution: an unmatched page is returned as unattributed, with an empty arena, so the gap stays
visible instead of being filled with a guess.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

UNATTRIBUTED = "unattributed"


def _path_segments(url: str) -> list[str]:
    try:
        return [
            segment.lstrip("@").casefold()
            for segment in urlparse(url).path.split("/")
            if segment
        ]
    except ValueError:
        return []


def match_account(
    rows: Iterable[Mapping[str, Any]], platform: str, platform_url: str
) -> Mapping[str, Any] | None:
    """The configured account row a captured page URL belongs to, or ``None``.

    A row matches when its platform agrees and its handle appears as a path segment of the page
    URL: ``x.com/@PauseAI``, ``x.com/PauseAI`` and the trailing-slash forms all resolve to the same
    row. Handles are compared case-folded with a leading ``@`` stripped, because the browser reports
    whichever form the site rendered.
    """
    segments = _path_segments(platform_url)
    if not segments:
        return None
    for row in rows:
        if str(row.get("platform") or "").casefold() != platform.casefold():
            continue
        handle = str(row.get("handle") or "").lstrip("@").casefold()
        if handle and handle in segments:
            return row
    return None


def attribution_for(
    rows: Iterable[Mapping[str, Any]], platform: str, platform_url: str
) -> dict[str, str]:
    """The attribution fields a captured record carries: account, source label, arena, group.

    ``account`` keeps the ``"name:handle"`` shape the capture server has always written, so an
    existing consumer does not need to change; ``arena`` and ``source_name`` are what the records
    were missing. All three are empty when nothing matched.
    """
    row = match_account(rows, platform, platform_url)
    if row is None:
        return {"account": UNATTRIBUTED, "source_name": "", "arena": "", "group_id": ""}
    name = str(row.get("name") or "")
    handle = str(row.get("handle") or "")
    return {
        "account": f"{name}:{handle}",
        "source_name": name,
        "arena": str(row.get("arena") or ""),
        "group_id": str(row.get("group_id") or ""),
    }
