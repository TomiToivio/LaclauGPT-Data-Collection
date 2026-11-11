"""Read-only stratification audit for the Phase 1 evaluation sample (#88).

`paper/PHASE_1_PAPER.md` §4.2 asks for an evaluation sample stratified across "the three arenas,
source types, languages, predicted formations, uncertain outputs, and abstentions", held apart from
prompt development and double-coded by two researchers. Measured against the AI26 corpus, most of
that grid is empty: Finnish is ~2 % of the frame, and the Finnish parliamentary cell has no
collectable first-party source.

This script does not pick a remedy. It measures the frame and reports **what each remedy would
cost**, so the owner's decision in #88 is a choice between quantified options rather than between
sentences:

1. declare a minimum per-cell size and pool the smaller cells;
2. demote Finnish to a robustness check;
3. extend the period / add Finnish elite sources;
4. restrict the agreement claim to `en × elites`.

Every number is computed from the store; nothing is written. The frame is the one the study declares
(`handoff.status = ready`, publication time inside the window), never the whole store — the whole
store contains ~5,000 records published before the window that can never enter a sample.

    python scripts/audit_evaluation_strata_88.py --json out.json
    python scripts/audit_evaluation_strata_88.py --min-cell 10 --min-cell 20
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_WINDOW_START = "2026-09-01T00:00:00+00:00"
DEFAULT_WINDOW_END = "2026-12-31T23:59:59+00:00"

#: The three arenas §4.2 names, plus the bucket the store actually contains.
ARENAS = ("elites", "grassroots", "parliamentary")
UNASSIGNED = "unassigned"

#: Coarse formation proxy: the coding either constructs a populist formula or it does not, and a
#: document with no stored coding is its own bucket — it cannot be stratified on what it does not have.
FORMATION_POPULIST = "populist"
FORMATION_NON_POPULIST = "non_populist"
FORMATION_UNCODED = "uncoded"

#: Cell sizes an evaluation design might declare as its minimum, from the smallest defensible
#: agreement cell upwards.
DEFAULT_MIN_CELLS = (5, 10, 15, 20, 30)


@dataclass
class StratumRow:
    """One document, reduced to the dimensions §4.2 stratifies on."""

    arena: str
    language: str
    platform: str
    formation: str
    uncertain: bool
    abstained: bool
    published_at: str
    source_type: str = ""
    country: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "arena": self.arena,
            "language": self.language,
            "platform": self.platform,
            "formation": self.formation,
            "uncertain": self.uncertain,
            "abstained": self.abstained,
            "published_at": self.published_at,
            "source_type": self.source_type,
            "country": self.country,
        }


def _labels(record: Mapping[str, Any]) -> tuple[str, str, str, str]:
    source = record.get("source") or {}
    arena = str(record.get("arena") or source.get("raw_metadata", {}).get("arena") or "").strip()
    language = str(source.get("language") or "").strip().casefold()
    platform = str(source.get("platform") or "").strip().casefold()
    country = str(record.get("country") or source.get("country") or "").strip().casefold()
    return (arena or UNASSIGNED, language or "unlabelled", platform or "unknown", country)


def formation_of(analysis: Mapping[str, Any] | None) -> str:
    """Coarse formation label from a stored analysis result.

    A document with no result, or a result whose analysis has no populism coding, is *uncoded* — not
    "non-populist". The difference matters: §4.2 wants abstentions and uncertain outputs to be a
    stratum, so silence may not be counted as a negative finding.
    """
    if not analysis:
        return FORMATION_UNCODED
    formula = analysis.get("formula_of_populism")
    if not isinstance(formula, Mapping) or not formula:
        return FORMATION_UNCODED
    if str(formula.get("collective_subject") or "").strip():
        return FORMATION_POPULIST
    return FORMATION_NON_POPULIST


def uncertain_or_abstained(analysis: Mapping[str, Any] | None) -> tuple[bool, bool]:
    if not isinstance(analysis, Mapping):
        return (False, False)
    return (bool(analysis.get("uncertainty")), bool(analysis.get("abstentions")))


def rows_from_documents(
    documents: Iterable[Mapping[str, Any]],
    analyses: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[StratumRow]:
    """Reduce stored records (plus any analysis results keyed by `source_url`) to stratum rows."""
    analyses = analyses or {}
    rows: list[StratumRow] = []
    for document in documents:
        url = str(document.get("source_url") or "")
        arena, language, platform, country = _labels(document)
        analysis = analyses.get(url)
        uncertain, abstained = uncertain_or_abstained(analysis)
        rows.append(
            StratumRow(
                arena=arena,
                language=language,
                platform=platform,
                formation=formation_of(analysis),
                uncertain=uncertain,
                abstained=abstained,
                published_at=str((document.get("handoff") or {}).get("published_at") or ""),
                source_type=str(
                    (document.get("source") or {}).get("raw_metadata", {}).get("source_name") or ""
                ),
                country=country,
            )
        )
    return rows


def cell_counts(
    rows: Sequence[StratumRow], *, dimensions: Sequence[str] = ("arena", "language", "formation")
) -> dict[tuple[str, ...], int]:
    counts: dict[tuple[str, ...], int] = defaultdict(int)
    for row in rows:
        counts[tuple(str(getattr(row, name)) for name in dimensions)] += 1
    return dict(counts)


def min_cell_feasibility(
    rows: Sequence[StratumRow], *, thresholds: Sequence[int] = DEFAULT_MIN_CELLS
) -> list[dict[str, Any]]:
    """For each declared minimum cell size: how many cells survive, and how much of the frame they hold.

    This is option 1 of #88 made concrete. A design that declares "at least N per cell, smaller cells
    pooled" is executable exactly when the surviving cells cover enough of the frame to be worth
    sampling, which is a number, not an opinion.
    """
    counts = cell_counts(rows)
    total = len(rows)
    report: list[dict[str, Any]] = []
    for threshold in thresholds:
        surviving = {cell: n for cell, n in counts.items() if n >= threshold}
        covered = sum(surviving.values())
        report.append(
            {
                "min_cell": int(threshold),
                "cells_total": len(counts),
                "cells_at_or_above": len(surviving),
                "documents_in_cells_at_or_above": covered,
                "share_of_frame": (covered / total) if total else 0.0,
                "cells_below": sorted(
                    [{"cell": list(cell), "n": n} for cell, n in counts.items() if n < threshold],
                    key=lambda item: (-item["n"], item["cell"]),
                ),
            }
        )
    return report


def language_profile(rows: Sequence) -> dict[str, Any]:
    """Option 2 and 4: how much is English, how much Finnish, and where the Finnish cells sit."""
    by_language = Counter(row.language for row in rows)
    fi = [row for row in rows if row.language == "fi"]
    fi_by_arena = Counter(row.arena for row in fi)
    fi_by_arena_platform = Counter((row.arena, row.platform) for row in fi)
    en_elites = [row for row in rows if row.language == "en" and row.arena == "elites"]
    return {
        "total": len(rows),
        "by_language": dict(sorted(by_language.items(), key=lambda item: -item[1])),
        "finnish_total": len(fi),
        "finnish_share": (len(fi) / len(rows)) if rows else 0.0,
        "finnish_by_arena": dict(sorted(fi_by_arena.items(), key=lambda item: -item[1])),
        "finnish_by_arena_platform": {
            f"{arena}/{platform}": n
            for (arena, platform), n in sorted(fi_by_arena_platform.items(), key=lambda i: -i[1])
        },
        "en_elites": {
            "documents": len(en_elites),
            "platforms": dict(sorted(Counter(r.platform for r in en_elites).items(), key=lambda i: -i[1])),
            "formations": dict(sorted(Counter(r.formation for r in en_elites).items(), key=lambda i: -i[1])),
            "uncertain": sum(1 for r in en_elites if r.uncertain),
            "abstained": sum(1 for r in en_elites if r.abstained),
        },
    }


def arena_profile(rows: Sequence) -> dict[str, Any]:
    by_arena = Counter(row.arena for row in rows)
    return {
        "by_arena": dict(sorted(by_arena.items(), key=lambda item: -item[1])),
        "unassigned": by_arena.get(UNASSIGNED, 0),
        "unassigned_share": (by_arena.get(UNASSIGNED, 0) / len(rows)) if rows else 0.0,
    }


def weekly_inflow(rows: Sequence) -> dict[str, dict[str, float]]:
    """Documents per week by arena, so option 3 ("extend the period") has a rate to multiply.

    The estimate is the frame's own rate over its own span: how long the *current* collection would
    need to reach a cell size, at the present intake.
    """
    stamps = sorted(row.published_at for row in rows if row.published_at)
    per_arena: dict[str, int] = defaultdict(int)
    for row in rows:
        per_arena[row.arena] += 1
    weeks = 1.0
    if len(stamps) >= 2:
        from datetime import datetime

        def parse(value: str) -> datetime | None:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None

        first, last = parse(stamps[0]), parse(stamps[-1])
        if first and last and last > first:
            weeks = max((last - first).total_seconds() / 604_800.0, 1 / 7)
    return {
        arena: {
            "documents": count,
            "per_week": count / weeks,
        }
        for arena, count in sorted(per_arena.items(), key=lambda item: -item[1])
    }


def build_report(
    rows: Sequence[StratumRow],
    *,
    window: tuple[str, str] = (DEFAULT_WINDOW_START, DEFAULT_WINDOW_END),
    thresholds: Sequence[int] = DEFAULT_MIN_CELLS,
) -> dict[str, Any]:
    """Everything #88's four options need in order to be chosen by arithmetic instead of taste."""
    return {
        "schema_version": "ai26.evaluation_strata/1",
        "window": {"since": window[0], "until": window[1]},
        "frame": {
            "documents": len(rows),
            "note": (
                "handoff.status=ready and publication time inside the window; the whole store is a "
                "different, larger number and must not be used as an evaluation denominator"
            ),
        },
        "arena": arena_profile(rows),
        "language": language_profile(rows),
        "inflow": weekly_inflow(rows),
        "min_cell": min_cell_feasibility(rows, thresholds=thresholds),
        "uncertainty": {
            "uncertain": sum(1 for row in rows if row.uncertain),
            "abstained": sum(1 for row in rows if row.abstained),
            "uncoded": sum(1 for row in rows if row.formation == FORMATION_UNCODED),
        },
        "option_checks": option_checks(rows),
    }


def option_checks(rows: Sequence[StratumRow]) -> dict[str, Any]:
    """One line per option in #88, answered with the frame rather than with a preference."""
    counts = cell_counts(rows)
    en_elites_coded = counts.get(("elites", "en", FORMATION_POPULIST), 0) + counts.get(
        ("elites", "en", FORMATION_NON_POPULIST), 0
    )
    en_elites_total = sum(
        count for cell, count in counts.items() if cell[0] == "elites" and cell[1] == "en"
    )
    fi_cells = {cell: n for cell, n in counts.items() if cell[1] == "fi"}
    return {
        "option_1_min_cell": (
            "executable for any threshold the table above shows as covering enough of the frame; "
            "the cells that fall below it are listed per threshold and must be pooled, not estimated"
        ),
        "option_2_demote_finnish": {
            "finnish_documents": sum(fi_cells.values()),
            "english_documents": sum(n for cell, n in counts.items() if cell[1] == "en"),
            "verdict": (
                "executable as a robustness check: Finnish can be reported as a cross-language "
                "illustration without an agreement statistic per cell"
            ),
        },
        "option_3_extend_or_add_sources": {
            "current_finnish_cells": {
                f"{cell[0]}/{cell[2]}": n for cell, n in sorted(fi_cells.items(), key=lambda i: -i[1])
            },
            "verdict": (
                "period extension alone multiplies a rate that is already thin per arena; it needs a "
                "source-selection decision (which Finnish elite and parliamentary sources to add), "
                "not more weeks of the same intake"
            ),
        },
        "option_4_restrict_to_en_elites": {
            "documents": en_elites_total,
            "coded_documents": en_elites_coded,
            "uncoded_documents": en_elites_total - en_elites_coded,
            "verdict": (
                "executable today, and honest, if §4.2 says plainly that agreement is claimed for "
                "the en x elites stratum only and that other strata are reported descriptively"
            ),
        },
    }


def load_rows_from_mongo(
    *,
    uri: str,
    database: str,
    project_id: str = "ai26",
    run_id: str | None = None,
    window: tuple[str, str] = (DEFAULT_WINDOW_START, DEFAULT_WINDOW_END),
    limit: int | None = None,
) -> list[StratumRow]:
    """Read the ready frame and any stored analysis results. Read-only by construction."""
    from pymongo import MongoClient

    client = MongoClient(uri)
    db = client[database]
    query: dict[str, Any] = {
        "project_id": project_id,
        "handoff.status": "ready",
        "handoff.published_at": {"$gte": window[0], "$lte": window[1]},
    }
    if run_id:
        query["handoff.run_id"] = run_id
    projection = {
        "_id": 0,
        "source_url": 1,
        "arena": 1,
        "country": 1,
        "handoff.published_at": 1,
        "source.language": 1,
        "source.platform": 1,
        "source.country": 1,
        "source.raw_metadata.arena": 1,
        "source.raw_metadata.source_name": 1,
    }
    cursor = db["ai26__records"].find(query, projection)
    if limit:
        cursor = cursor.limit(limit)
    documents = list(cursor)
    urls = [str(document.get("source_url") or "") for document in documents if document.get("source_url")]
    analyses: dict[str, Mapping[str, Any]] = {}
    if urls:
        for result in db["ai26__analysis_results"].find(
            {"project_id": project_id, "source_url": {"$in": urls}},
            {"_id": 0, "source_url": 1, "result.analysis": 1},
        ):
            analyses[str(result.get("source_url") or "")] = (result.get("result") or {}).get("analysis") or {}
    client.close()
    return rows_from_documents(documents, analyses)


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# AI26 evaluation-sample stratification audit (#88)",
        "",
        f"Window: `{report['window']['since']}` .. `{report['window']['until']}`  ",
        f"Frame: **{report['frame']['documents']:,}** documents (`handoff.status=ready`)",
        "",
        "## Arenas",
        "",
        "| arena | documents |",
        "| --- | --- |",
    ]
    for arena, count in report["arena"]["by_arena"].items():
        lines.append(f"| {arena} | {count:,} |")
    lines += [
        "",
        f"Unassigned: {report['arena']['unassigned']:,} "
        f"({report['arena']['unassigned_share']:.1%}) — these cannot enter an arena-stratified sample.",
        "",
        "## Languages",
        "",
        "| language | documents |",
        "| --- | --- |",
    ]
    for language, count in report["language"]["by_language"].items():
        lines.append(f"| {language} | {count:,} |")
    lines += [
        "",
        f"Finnish by arena: {report['language']['finnish_by_arena']}",
        "",
        "## Minimum cell size (option 1)",
        "",
        "| min cell | cells ≥ min | documents covered | share of frame |",
        "| --- | --- | --- | --- |",
    ]
    for row in report["min_cell"]:
        lines.append(
            f"| {row['min_cell']} | {row['cells_at_or_above']} / {row['cells_total']} | "
            f"{row['documents_in_cells_at_or_above']:,} | {row['share_of_frame']:.1%} |"
        )
    option_four = report["option_checks"]["option_4_restrict_to_en_elites"]
    lines += [
        "",
        "## Options",
        "",
        f"- **1. minimum cell size** — {report['option_checks']['option_1_min_cell']}",
        f"- **2. demote Finnish** — {report['option_checks']['option_2_demote_finnish']['verdict']}",
        f"- **3. extend or add sources** — {report['option_checks']['option_3_extend_or_add_sources']['verdict']}",
        f"- **4. restrict to en × elites** — {option_four['documents']:,} documents, of which "
        f"{option_four['coded_documents']:,} carry a stored formation; "
        f"{report['option_checks']['option_4_restrict_to_en_elites']['verdict']}",
        "",
        "## Uncertainty and abstention",
        "",
        f"uncertain {report['uncertainty']['uncertain']:,} · "
        f"abstained {report['uncertainty']['abstained']:,} · "
        f"uncoded {report['uncertainty']['uncoded']:,}",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audit-evaluation-strata-88", description=__doc__)
    parser.add_argument("--mongodb-uri", default=os.environ.get("LACLAUGPT_MONGODB_URI"))
    parser.add_argument(
        "--database", default=os.environ.get("LACLAUGPT_MONGODB_DATABASE", "spectacleScraper")
    )
    parser.add_argument("--project", default="ai26")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--since", default=DEFAULT_WINDOW_START)
    parser.add_argument("--until", default=DEFAULT_WINDOW_END)
    parser.add_argument("--min-cell", type=int, action="append", default=None)
    parser.add_argument("--json", default=None, help="write the report here")
    parser.add_argument("--markdown", default=None, help="write the rendered audit here")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.mongodb_uri:
        parser.error("--mongodb-uri or LACLAUGPT_MONGODB_URI is required")
    thresholds = tuple(args.min_cell) if args.min_cell else DEFAULT_MIN_CELLS
    rows = load_rows_from_mongo(
        uri=args.mongodb_uri,
        database=args.database,
        project_id=args.project,
        run_id=args.run_id,
        window=(args.since, args.until),
    )
    report = build_report(rows, window=(args.since, args.until), thresholds=thresholds)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as handle:
            handle.write(render_markdown(report))
    print(render_markdown(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
