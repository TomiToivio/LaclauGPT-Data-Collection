# -*- coding: utf-8 -*-
"""Issue #338 — a failing media object must name its reason in the cycle summary.

The AI26 media stage re-attempts the same two poison objects every hour. The
hourly summary line carried only ``failed: 2``, so a cron log could not say
*which* objects failed or *why* — every investigation had to re-derive it from
the durable media index. The downloader already computes a sanitized reason
(an HTTP code or an exception class name; never exception detail, never a
signed URL), so the fix is only to stop discarding it.

These are pure-function tests: no Mongo, no S3, no network, no downloads.
"""
from __future__ import annotations

from pathlib import Path

from laclaugpt_data_collection.distributed_media_runner import _failure_details

RUNNER = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "laclaugpt_data_collection"
    / "distributed_media_runner.py"
)


def _row(status: str, key: str, error: str = "", http_status=None) -> dict:
    return {
        "media_key": key,
        "collection_id": "ai26",
        "status": status,
        "error": error,
        "http_status": http_status,
    }


class TestFailureDetails:
    def test_failed_object_carries_its_reason(self) -> None:
        results = [_row("failed", "ai26:youtube:abc:0", "HTTP 404", 404)]

        details = _failure_details(results)

        assert details == [
            {
                "media_key": "ai26:youtube:abc:0",
                "status": "failed",
                "error": "HTTP 404",
                "http_status": 404,
            }
        ], "a failed object must report which object it is and why it failed"

    def test_access_restricted_is_reported_too(self) -> None:
        """A terminal-but-not-completed state is still a stall if it repeats."""
        results = [_row("access_restricted", "ai26:tiktok:xyz:0", "HTTP 403")]

        details = _failure_details(results)

        assert [row["status"] for row in details] == ["access_restricted"]

    def test_completed_and_skipped_objects_are_not_listed(self) -> None:
        results = [
            _row("completed", "ai26:arxiv:a:0"),
            _row("skipped", "ai26:arxiv:b:0"),
            _row("failed", "ai26:arxiv:c:0", "URLError"),
        ]

        details = _failure_details(results)

        assert [row["media_key"] for row in details] == ["ai26:arxiv:c:0"], (
            "only objects that did not resolve belong in the failure list"
        )

    def test_a_clean_cycle_reports_an_empty_list(self) -> None:
        assert _failure_details([_row("completed", "ai26:arxiv:a:0")]) == []

    def test_the_list_is_bounded_so_an_outage_cannot_flood_the_log(self) -> None:
        results = [_row("failed", f"ai26:arxiv:{i:03d}:0", "HTTP 500") for i in range(60)]

        details = _failure_details(results, limit=25)

        assert len(details) == 25, "the reason list is a diagnostic, not a data export"

    def test_ordering_is_stable_between_identical_cycles(self) -> None:
        """Hourly cycles must be diffable: same failures, same order."""
        results = [
            _row("failed", "ai26:b:0", "HTTP 500"),
            _row("failed", "ai26:a:0", "HTTP 404"),
            _row("access_restricted", "ai26:c:0", "HTTP 403"),
        ]

        first = _failure_details(results)
        second = _failure_details(list(reversed(results)))

        assert first == second
        assert [row["media_key"] for row in first] == ["ai26:c:0", "ai26:a:0", "ai26:b:0"]

    def test_a_row_missing_its_error_does_not_crash_the_cycle(self) -> None:
        """Old result rows or a future downloader change must not break the stage."""
        assert _failure_details([{"status": "failed"}]) == [
            {"media_key": "", "status": "failed", "error": "", "http_status": None}
        ]


class TestRunnerWiresTheDiagnostic:
    """Both runners must emit it, or one deployment path stays blind."""

    def test_both_summaries_carry_the_failure_list(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        local = source[source.index("def _run_local_media_unlocked("):
                       source.index("def _run_distributed_media_unlocked(")]
        distributed = source[source.index("def _run_distributed_media_unlocked("):]

        assert '"failures": _failure_details(results)' in local
        assert '"failures": _failure_details(results)' in distributed
