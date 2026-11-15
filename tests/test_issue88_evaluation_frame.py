"""Meta #88: the §4.2 evaluation sample has to be shown to be drawable, not assumed to be.

The issue rules on a sampling frame, and the failure it reports is a shape, not a shortage: the
Finnish cells are 16 / 69 / 51 across three arenas, and 24 % of the corpus carries no arena at all.
A report that only prints totals cannot show that, so these tests pin the three properties a reader
needs before trusting the numbers — the frame excludes what cannot be evaluated, an arena-less record
is named rather than dropped, and the minimum-cell table says what enforcing a cell size would cost.
"""
from __future__ import annotations

from laclaugpt_data_collection.evaluation_frame import (
    NO_ARENA,
    NO_LANGUAGE,
    evaluation_frame_report,
    formation_coverage,
    frame_records,
    stratify,
)

WINDOW = {"window_start": "2026-09-01", "window_end": "2026-12-31"}


def record(*, arena="elites", language="en", published="2026-10-15T09:00:00Z",
           source_type="first_party", platform="rss", url="https://example.invalid/1"):
    return {
        "source_url": url,
        "arena": arena,
        "source": {"language": language, "platform": platform, "source_type": source_type},
        "handoff": {"status": "ready", "published_at": published},
    }


def test_the_frame_drops_documents_that_can_never_be_evaluated_and_says_why():
    rows = [
        record(url="a"),
        record(url="b", published="2026-08-31T23:59:59Z"),   # before the window
        record(url="c", published="2027-01-01T00:00:00Z"),   # after it
        record(url="d", published=""),
    ]
    frame = frame_records(rows, **WINDOW)
    assert frame["total"] == 4
    assert frame["in_window"] == 1
    assert frame["excluded"] == {"before_or_after_window": 2, "missing_publication_time": 1}


def test_an_rfc_2822_publication_time_is_parsed_rather_than_read_as_out_of_window():
    """The store carries both formats; comparing the first ten characters rejects one of them.

    This is not hypothetical: on 2026-11-11 the live ready frame held 1,889 records whose
    `source.created_at` is RFC 2822, and a string-prefix comparison silently moved all of them out
    of the declared window.
    """
    rfc = record(url="rfc", published="Wed, 11 Nov 2026 12:49:12 +0000")
    iso = record(url="iso", published="2026-11-11T12:49:12+00:00")
    old = record(url="old", published="Sun, 30 Aug 2026 23:00:00 +0000")
    frame = frame_records([rfc, iso, old], **WINDOW)
    assert frame["in_window"] == 2, "both formats describe the same day and both are in the window"
    assert frame["excluded"]["before_or_after_window"] == 1


def test_an_arena_less_record_is_named_not_silently_dropped():
    rows = [record(url="a"), record(url="b", arena=""), record(url="c", arena="")]
    report = evaluation_frame_report(rows, **WINDOW)
    assert report["arena_less"]["total"] == 2
    assert report["arena_less"]["by_platform"] == {"rss": 2}
    assert NO_ARENA in report["arena_language"], "the arena-less block must appear on the grid"


def test_the_grid_counts_the_finnish_cells_the_issue_argues_about():
    rows = (
        [record(url=f"e{i}", arena="elites", language="fi") for i in range(16)]
        + [record(url=f"g{i}", arena="grassroots", language="fi") for i in range(9)]
        + [record(url=f"p{i}", arena="parliamentary", language="fi") for i in range(5)]
        + [record(url=f"n{i}", arena="en") for i in range(40)]
    )
    report = evaluation_frame_report(rows, **WINDOW)
    assert report["finnish"] == {"total": 30, "by_arena": {"elites": 16, "grassroots": 9, "parliamentary": 5}}
    assert report["arena_language"]["elites"]["fi"] == 16
    assert report["arena_language"]["elites"].get("en", 0) == 0, "no English row was planted in elites"


def test_a_missing_language_is_its_own_column_rather_than_english():
    report = evaluation_frame_report([record(language="")], **WINDOW)
    assert report["arena_language"]["elites"] == {NO_LANGUAGE: 1}


def test_the_minimum_cell_table_says_what_a_required_cell_size_costs():
    """Two is the smallest cell that can carry an agreement statistic; ten is a comfortable one."""
    rows = (
        [record(url=f"a{i}", arena="elites", language="en", source_type="first_party") for i in range(12)]
        + [record(url=f"b{i}", arena="elites", language="fi", source_type="first_party") for i in range(3)]
        + [record(url=f"c{i}", arena="grassroots", language="en", source_type="scholarly") for i in range(1)]
    )
    report = evaluation_frame_report(rows, **WINDOW)
    feasibility = {row["minimum"]: row for row in report["stratification"]["feasibility"]}

    assert feasibility[2]["cells"] == 2, "12 and 3 survive; the singleton does not"
    assert feasibility[2]["records_in_surviving_cells"] == 15
    assert feasibility[2]["records_outside_surviving_cells"] == 1
    assert feasibility[5]["cells"] == 1
    assert feasibility[10]["cells"] == 1 and feasibility[10]["records_in_surviving_cells"] == 12
    assert report["stratification"]["singletons"] == 1


def test_coverage_is_a_share_of_the_frame_not_of_the_surviving_cells():
    rows = [record(url=f"x{i}", source_type="first_party") for i in range(4)] + [
        record(url="y", language="fi", source_type="scholarly")
    ]
    feasibility = {row["minimum"]: row for row in stratify(rows, minimum_sizes=(2,))["feasibility"]}
    assert feasibility[2]["coverage"] == 0.8, "4 of 5, not 4 of 4"


def test_formation_coverage_reports_an_open_label_space_instead_of_hiding_it():
    labels = {
        "u1": ["critical_ai", "accelerative"],
        "u2": ["critical_ai"],
        "u3": [],
        "u4": ["Anti-Oligarchy Movement"],
    }
    report = formation_coverage(labels, core=("critical_ai", "ai_safety"))
    assert report["analysed"] == 4
    assert report["with_any_formation"] == 3
    assert report["with_core_formation"] == 2
    assert report["distinct_labels"] == 3
    assert report["top_labels"][0] == {"label": "critical_ai", "count": 2}


def test_the_report_carries_the_window_it_was_measured_against():
    report = evaluation_frame_report([record()], **WINDOW)
    assert report["window"] == {"start": "2026-09-01", "end": "2026-12-31"}
    assert "stratification" in report and "arena_source_type" in report
