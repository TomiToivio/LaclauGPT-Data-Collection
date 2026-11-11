"""Can the Phase 1 §4.2 evaluation sample actually be stratified? (meta #88)

§4.2 asks for an evaluation sample stratified across "the three arenas, source types, languages,
predicted formations, uncertain outputs, and abstentions". A stratification requirement is only
executable if the cells it names are populated, so this module answers a single question with counts:
**which cells exist, how small are they, and what does enforcing a minimum cell size cost?**

It is deliberately an *audit*, not a sampling design. It reports; it never picks a minimum cell size,
demotes a language, or redefines a stratum — those are decisions for the paper's owner, and the
numbers here are what such a decision has to be made against.

Two properties matter for the answer to be usable:

* the frame is the **declared window and the analysis-ready set**, because a cell count over the whole
  store includes documents that can never enter the evaluation sample (pre-window, undated, waiting
  for media);
* an empty cell and a cell with one document are different failures. Agreement between two coders
  needs two, so the feasibility table reports the number of cells at or above a candidate minimum and
  the share of the frame they carry, rather than a single cell count.

Read-only: callers pass records in, nothing here opens a store or writes to one.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from .corpus_audit import (
    record_arena,
    record_language,
    record_platform,
    record_publication,
)

#: The arena label used when a record carries none. It is reported, never silently dropped: a
#: stratified draw that respects arena membership loses this whole block.
NO_ARENA = "(none)"

#: A record with no language label cannot be placed on the language axis, for the same reason.
NO_LANGUAGE = "(none)"

#: Candidate minimum cell sizes. Two is the smallest cell that can carry an inter-coder agreement
#: statistic at all, which is why it leads.
DEFAULT_MINIMUM_SIZES: tuple[int, ...] = (2, 3, 5, 10)


def record_source_type(record: dict[str, Any]) -> str:
    """Source type as declared by the collection layer, '' when absent."""
    for path in (("source_type",), ("source", "source_type")):
        node: Any = record
        for key in path:
            node = node.get(key) if isinstance(node, Mapping) else None
        if isinstance(node, str) and node.strip():
            return node.strip()
    return ""


def publication_date(published: str) -> date | None:
    """Parse the publication time the record carries, in either format the store uses.

    ``source.created_at`` holds RFC 2822 (``Wed, 11 Nov 2026 12:49:12 +0000``) while
    ``handoff.published_at`` holds ISO 8601, and a comparison on the first ten characters of the
    string therefore reads every RFC 2822 record as out of window. The analysis side already
    normalises both (``laclaugpt_data_analysis/canonical.py``); an audit that does not is not
    measuring the frame the study declares.
    """
    text = (published or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return parsed.date() if parsed else None


def _in_window(published: str, start: str, end: str) -> bool:
    """Whole-day window membership, in whichever format the timestamp arrived."""
    day = publication_date(published)
    if day is None:
        return False
    lower = publication_date(start)
    upper = publication_date(end)
    return bool(lower and upper and lower <= day <= upper)


def frame_records(
    records: Iterable[dict[str, Any]], *, window_start: str, window_end: str
) -> dict[str, Any]:
    """Split records into the evaluation frame and the reasons the rest cannot join it.

    The order of the exclusions matters: a record outside the window is not also counted as undated,
    so the buckets sum to the input size and a reader can check the arithmetic.
    """
    excluded = {"before_or_after_window": 0, "missing_publication_time": 0}
    kept: list[dict[str, Any]] = []
    total = 0
    for record in records:
        total += 1
        published = record_publication(record)
        if not published or len(published) < 10:
            excluded["missing_publication_time"] += 1
            continue
        if not _in_window(published, window_start, window_end):
            excluded["before_or_after_window"] += 1
            continue
        kept.append(record)
    return {"total": total, "in_window": len(kept), "excluded": excluded, "records": kept}


def _grid(records: Sequence[dict[str, Any]], rows: str, columns: str) -> dict[str, dict[str, int]]:
    grid: dict[str, dict[str, int]] = {}
    for record in records:
        if rows == "arena":
            row = record_arena(record) or NO_ARENA
        elif rows == "language":
            row = record_language(record) or NO_LANGUAGE
        else:  # pragma: no cover - guarded by the caller
            raise ValueError(f"unknown grid row axis: {rows}")
        if columns == "language":
            column = record_language(record) or NO_LANGUAGE
        elif columns == "source_type":
            column = record_source_type(record) or "(untyped)"
        elif columns == "platform":
            column = record_platform(record) or "(unknown)"
        else:  # pragma: no cover
            raise ValueError(f"unknown grid column axis: {columns}")
        grid.setdefault(row, {}).setdefault(column, 0)
        grid[row][column] += 1
    return {row: dict(sorted(columns_.items(), key=lambda item: (-item[1], item[0])))
            for row, columns_ in sorted(grid.items())}


def stratify(
    records: Sequence[dict[str, Any]],
    *,
    minimum_sizes: Iterable[int] = DEFAULT_MINIMUM_SIZES,
    axes: tuple[str, ...] = ("arena", "language", "source_type"),
) -> dict[str, Any]:
    """Cell feasibility for the stratification §4.2 names.

    ``axes`` is the cross-tabulation that has to be populated: the default is the full three-way
    arena x language x source-type cell, which is the strictest reading of the method section. The
    table answers "if the evaluation sample demanded m documents in every cell, how much of the frame
    could it use, and how many cells would have to be pooled?"
    """
    cells: Counter[tuple[str, ...]] = Counter()
    for record in records:
        cells[tuple(
            (record_arena(record) or NO_ARENA) if axis == "arena" else
            (record_language(record) or NO_LANGUAGE) if axis == "language" else
            (record_source_type(record) or "(untyped)") if axis == "source_type" else
            (record_platform(record) or "(unknown)")
            for axis in axes
        )] += 1

    total = len(records)
    feasibility = []
    for minimum in minimum_sizes:
        surviving = {cell: count for cell, count in cells.items() if count >= minimum}
        covered = sum(surviving.values())
        feasibility.append({
            "minimum": minimum,
            "cells": len(surviving),
            "cells_total": len(cells),
            "records_in_surviving_cells": covered,
            "coverage": (covered / total) if total else 0.0,
            "records_outside_surviving_cells": total - covered,
        })

    return {
        "axes": list(axes),
        "records": total,
        "cells_total": len(cells),
        "cells": [
            {"cell": dict(zip(axes, cell)), "count": count}
            for cell, count in sorted(cells.items(), key=lambda item: (-item[1], item[0]))
        ],
        "feasibility": feasibility,
        "singletons": sum(1 for count in cells.values() if count == 1),
        "empty_cells_note": (
            "empty cells cannot be listed: the axes are taken from the data, so a cell with no "
            "records has no name here. The feasibility table is the honest form of the question."
        ),
    }


def formation_coverage(
    labels_by_url: dict[str, Iterable[str]], *, core: Iterable[str] = ()
) -> dict[str, Any]:
    """How much of the analysed frame carries a formation label, and how concentrated it is.

    ``labels_by_url`` maps ``source_url`` to the formation labels a model proposed for it. The
    unmapped count is reported rather than hidden: a codebook of seven entries that produces
    thousands of distinct strings is itself evidence about the "predicted formations" axis, because a
    stratified sample cannot be drawn on a label space that is not closed.
    """
    counts: Counter[str] = Counter()
    analysed = 0
    with_any = 0
    core_set = {item.strip().lower() for item in core if item.strip()}
    with_core = 0
    for labels in labels_by_url.values():
        analysed += 1
        items = [str(label).strip() for label in labels if str(label).strip()]
        if items:
            with_any += 1
        if core_set and any(item.lower() in core_set for item in items):
            with_core += 1
        counts.update(items)
    return {
        "analysed": analysed,
        "with_any_formation": with_any,
        "with_core_formation": with_core if core_set else None,
        "distinct_labels": len(counts),
        "top_labels": [{"label": label, "count": count}
                       for label, count in counts.most_common(15)],
    }


def evaluation_frame_report(
    records: Iterable[dict[str, Any]],
    *,
    window_start: str,
    window_end: str,
    labels_by_url: dict[str, Iterable[str]] | None = None,
    core_formations: Iterable[str] = (),
    minimum_sizes: Iterable[int] = DEFAULT_MINIMUM_SIZES,
) -> dict[str, Any]:
    """The whole #88 answer: frame, grid, feasibility, formation coverage."""
    frame = frame_records(records, window_start=window_start, window_end=window_end)
    kept = frame.pop("records")
    arena_language = _grid(kept, "arena", "language")
    report: dict[str, Any] = {
        "window": {"start": window_start, "end": window_end},
        "frame": frame,
        "arena_language": arena_language,
        "arena_source_type": _grid(kept, "arena", "source_type"),
        "arena_less": {
            "total": sum(arena_language.get(NO_ARENA, {}).values()),
            "by_platform": dict(Counter(
                record_platform(record) or "(unknown)"
                for record in kept if not record_arena(record)
            ).most_common()),
        },
        "finnish": {
            "total": sum(row.get("fi", 0) for row in arena_language.values()),
            "by_arena": {arena: row["fi"] for arena, row in arena_language.items() if row.get("fi")},
        },
        "stratification": stratify(kept, minimum_sizes=minimum_sizes),
    }
    if labels_by_url is not None:
        report["formations"] = formation_coverage(labels_by_url, core=core_formations)
    return report


def summary(report: dict[str, Any]) -> str:
    """A short terminal rendering; the JSON is the artefact, this is for a log line."""
    frame = report["frame"]
    lines = [
        f"window {report['window']['start']}..{report['window']['end']}",
        f"records {frame['total']}, in window {frame['in_window']}, "
        f"excluded {frame['excluded']}",
        "",
        "arena x language",
    ]
    for arena, columns in report["arena_language"].items():
        rendered = ", ".join(f"{name} {count}" for name, count in columns.items())
        lines.append(f"  {arena:<15} {rendered}")
    lines.append("")
    lines.append("minimum cell size (arena x language x source type)")
    for row in report["stratification"]["feasibility"]:
        lines.append(
            f"  >= {row['minimum']:<3} cells {row['cells']}/{row['cells_total']} "
            f"records {row['records_in_surviving_cells']} "
            f"({row['coverage']:.1%} of frame)"
        )
    return "\n".join(lines)
