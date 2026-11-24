"""Issue #470 — an undeclared stratum must not be able to hide behind a clean declared plan.

The audit already asked *"is every declared source present?"*. It could not ask the inverse: *"is every
source present declared?"*. In AI26 the answer was no — 609 records from eleven elite X handles, arriving
through a separate bridge, with no `source.platform`, no `source_name` and no arena, while `manifest_drift`
reported `in_sync` because the deployed manifest and the tracked plan agreed with each other and neither
described the bridge.

These tests pin the properties that make the new counter trustworthy:

* it counts authors, and says how many records they brought;
* it is case- and `@`-insensitive, because a capture records whichever form the page rendered;
* a blank author is a separate known bucket, not an undeclared one;
* it reports and never resolves — declaring a handle or recording it as out-of-plan is a sampling
  decision, so the audit must not choose;
* it is **not checked** when no declared list was supplied, so an unrun check cannot read as an all-clear.

Synthetic fixtures only; no private handles appear here.
"""
from __future__ import annotations

from laclaugpt_data_collection.corpus_audit import audit_records, audit_summary


def _rec(*, author: str = "", platform: str = "x", arena: str = "", source_name: str = "") -> dict:
    return {
        "source_url": f"https://x.com/{author or 'unknown'}/status/1",
        "platform": platform,
        "arena": arena,
        "language": "en",
        "source": {
            "platform": platform,
            "author": author,
            "language": "en",
            "created_at": "2026-01-01T00:00:00Z",
            "raw_metadata": {"source_name": source_name},
        },
    }


class TestUndeclaredStratumIsVisible:
    def test_an_author_no_declared_source_names_is_reported_with_its_record_count(self) -> None:
        records = [_rec(author="alpha") for _ in range(3)] + [_rec(author="beta")]
        report = audit_records(records, configured_sources=["alpha"])

        assert report["configured_sources"]["undeclared_checked"] is True
        assert report["configured_sources"]["undeclared"] == ["beta"]
        assert report["configured_sources"]["undeclared_count"] == 1
        assert report["configured_sources"]["undeclared_records"] == 1

    def test_several_undeclared_handles_are_listed_with_their_total(self) -> None:
        records = [_rec(author="alpha") for _ in range(2)]
        records += [_rec(author="gamma"), _rec(author="gamma"), _rec(author="delta")]
        report = audit_records(records, configured_sources=["alpha"])

        assert report["configured_sources"]["undeclared"] == ["delta", "gamma"]
        assert report["configured_sources"]["undeclared_records"] == 3

    def test_a_declared_author_is_not_reported(self) -> None:
        report = audit_records([_rec(author="alpha")], configured_sources=["alpha"])
        assert report["configured_sources"]["undeclared"] == []
        assert report["configured_sources"]["undeclared_records"] == 0

    def test_at_sign_and_case_do_not_create_a_false_positive(self) -> None:
        """A capture records @Alpha or alpha depending on what the page rendered."""
        records = [_rec(author="@Alpha"), _rec(author="ALPHA")]
        report = audit_records(records, configured_sources=["alpha"])
        assert report["configured_sources"]["undeclared"] == []

    def test_a_declared_source_name_may_be_written_with_an_at_sign(self) -> None:
        records = [_rec(author="alpha")]
        report = audit_records(records, configured_sources=["@Alpha"])
        assert report["configured_sources"]["undeclared"] == []


class TestTheCounterCannotFakeAnAllClear:
    def test_without_a_declared_list_the_check_is_marked_unrun(self) -> None:
        report = audit_records([_rec(author="alpha")])
        entry = report["configured_sources"]
        assert entry["undeclared_checked"] is False
        assert entry["undeclared_count"] is None, "None, not 0: an unrun check is not a clean result"
        assert entry["undeclared_records"] is None
        assert entry["undeclared"] == []

    def test_the_summary_says_nothing_about_undeclared_authors_when_unchecked(self) -> None:
        summary = audit_summary(audit_records([_rec(author="alpha")]))
        assert "undeclared" not in summary

    def test_the_summary_names_both_counts_when_checked(self) -> None:
        summary = audit_summary(audit_records([_rec(author="alpha")], configured_sources=["alpha"]))
        assert "0 undeclared author(s) contributing 0 record(s)" in summary


class TestItReportsRatherThanResolves:
    def test_an_undeclared_author_is_not_removed_from_the_totals(self) -> None:
        """Neither declaring nor discarding is the audit's call, so nothing is filtered out."""
        records = [_rec(author="alpha"), _rec(author="beta")]
        report = audit_records(records, configured_sources=["alpha"])
        assert report["total"] == 2, "records must still be counted"
        assert sum(entry["count"] for entry in report["by_author"]["ranked"]) == 2

    def test_an_undeclared_author_is_not_assigned_an_arena(self) -> None:
        """#470's records have no arena; the audit must keep them in the blank bucket."""
        records = [_rec(author="beta", arena="")]
        report = audit_records(records, configured_sources=["alpha"])
        assert report["by_arena"]["counts"]["(blank)"] == 1
        assert report["by_arena"]["shares"].get("elites", 0.0) == 0.0

    def test_a_blank_author_is_its_own_bucket_not_an_undeclared_handle(self) -> None:
        records = [_rec(author=""), _rec(author="alpha")]
        report = audit_records(records, configured_sources=["alpha"])
        assert report["configured_sources"]["undeclared"] == []
        ranked = {entry["name"]: entry["count"] for entry in report["by_author"]["ranked"]}
        assert ranked["(blank)"] == 1
