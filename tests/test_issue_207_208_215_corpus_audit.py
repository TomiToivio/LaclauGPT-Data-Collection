# -*- coding: utf-8 -*-
"""Issue #207/#208/#215 — the coverage and concentration audit must not lie.

All three open issues measure the same store:
#215 (3 sources = 50%, Bluesky = 2 timelines), #208 (grassroots 1.9%, Finnish 4,
4 platforms empty), #207 (nominal X stratum, blank arena, off-floor records).

Each needed an ad-hoc script to reproduce. `corpus_audit` makes them measurable in
one deterministic pass. These tests pin the properties that make a number from it
trustworthy: **no silent dropping** (blank/unknown stays a bucket), a **named
denominator**, and **no invented verdict** (it reports counts and shares, never a
threshold judgement).

Synthetic fixtures only.
"""
from __future__ import annotations

from laclaugpt_data_collection.corpus_audit import (
    audit_records,
    audit_summary,
    record_arena,
    record_author,
    record_language,
    record_platform,
    record_source_name,
)


def _rec(
    *,
    url: str = "https://example.invalid/1",
    platform: str = "rss",
    arena: str = "",
    language: str = "",
    source_name: str = "",
    author: str = "",
    published: str = "",
) -> dict:
    return {
        "source_url": url,
        "platform": platform,
        "arena": arena,
        "language": language,
        "source": {
            "platform": platform,
            "author": author,
            "language": language,
            "created_at": published,
            "raw_metadata": {"source_name": source_name},
        },
    }


class TestFieldExtraction:
    def test_reads_platform_arena_language_source_and_author(self) -> None:
        r = _rec(platform="bluesky", arena="elites", language="en",
                 source_name="Timnit Gebru", author="timnitgebru.blacksky.app")
        assert record_platform(r) == "bluesky"
        assert record_arena(r) == "elites"
        assert record_language(r) == "en"
        assert record_source_name(r) == "Timnit Gebru"
        assert record_author(r) == "timnitgebru.blacksky.app"

    def test_arena_falls_back_to_provenance_metadata(self) -> None:
        r = {"source_url": "u", "provenance": [{"metadata": {"arena": "grassroots"}}]}
        assert record_arena(r) == "grassroots"

    def test_missing_fields_are_empty_not_invented(self) -> None:
        r = {"source_url": "u"}
        assert record_arena(r) == ""
        assert record_platform(r) == ""
        assert record_language(r) == ""


class TestNoSilentDropping:
    def test_blank_arena_is_a_named_bucket_not_dropped(self) -> None:
        """#207: arena is '' on every X record. That must be visible."""
        records = [_rec(arena=""), _rec(arena="elites")]
        report = audit_records(records)
        assert report["total"] == 2
        assert report["by_arena"]["counts"]["(blank)"] == 1
        assert report["by_arena"]["unknown"] == 1
        assert sum(report["by_arena"]["counts"].values()) == 2, "no record dropped"

    def test_records_without_language_are_counted_not_dropped(self) -> None:
        """#208: 64% of the corpus carries no language; the audit must say so."""
        records = [_rec(language=""), _rec(language=""), _rec(language="en")]
        report = audit_records(records)
        assert report["by_language"]["unlabelled"] == 2

    def test_every_bucket_sum_equals_the_total(self) -> None:
        records = [
            _rec(platform="rss", arena="elites", language="en", source_name="a"),
            _rec(platform="bluesky", arena="grassroots", source_name=""),
            _rec(platform="x", arena=""),
        ]
        report = audit_records(records)
        assert sum(report["by_platform"]["counts"].values()) == report["total"]
        assert sum(report["by_arena"]["counts"].values()) == report["total"]
        assert sum(report["by_language"]["counts"].values()) == report["total"]
        assert sum(e["count"] for e in report["by_source"]["ranked"]) == report["total"]


class TestConcentration:
    def test_top_n_share_matches_the_hand_count(self) -> None:
        """#215: 3 sources = 50%. The arithmetic must be checkable by hand."""
        records = (
            [_rec(source_name="big")] * 3
            + [_rec(source_name="mid")] * 2
            + [_rec(source_name="small")] * 1
        )
        report = audit_records(records, top_n=2)
        assert report["total"] == 6
        assert report["concentration"]["top_n_names"] == ["big", "mid"]
        assert report["concentration"]["top_n_share"] == 5 / 6

    def test_top_n_names_are_ordered_by_count(self) -> None:
        records = [_rec(source_name="b")] * 2 + [_rec(source_name="a")] * 5
        report = audit_records(records, top_n=2)
        assert report["concentration"]["top_n_names"] == ["a", "b"]

    def test_per_platform_author_concentration_is_separate(self) -> None:
        """#215: the Bluesky stratum being two timelines is its own finding."""
        records = (
            [_rec(platform="bluesky", author="one")] * 4
            + [_rec(platform="bluesky", author="two")] * 2
            + [_rec(platform="rss", author="")] * 3
        )
        report = audit_records(records)
        bluesky = report["by_author"]["per_platform"]["bluesky"]
        assert [e["name"] for e in bluesky] == ["one", "two"]
        assert bluesky[0]["count"] == 4

    def test_the_denominator_is_named(self) -> None:
        report = audit_records([_rec(), _rec()])
        assert report["denominator"]["records"] == 2
        assert report["concentration"]["denominator"] == 2


class TestDeclaredPlatformsAndFloor:
    def test_declared_but_empty_platforms_are_listed(self) -> None:
        """#208: youtube/mastodon/tiktok/instagram declared but produce nothing."""
        report = audit_records([_rec(platform="rss"), _rec(platform="arxiv")])
        empty = report["by_platform"]["declared_but_empty"]
        for platform in ("youtube", "mastodon", "tiktok", "instagram"):
            assert platform in empty
        assert "rss" not in empty

    def test_off_floor_records_are_counted(self) -> None:
        """#207: 12 X records predate the 2026-09-01 floor."""
        records = [
            _rec(published="2019-09-03T00:00:00Z"),
            _rec(published="2026-07-20T00:00:00Z"),
            _rec(published="2026-09-16T00:00:00Z"),
        ]
        report = audit_records(records, publication_floor="2026-09-01")
        assert report["publication_floor"]["off_floor"] == 2

    def test_no_floor_means_no_off_floor_count(self) -> None:
        report = audit_records([_rec(published="2019-01-01T00:00:00Z")])
        assert report["publication_floor"]["off_floor"] == 0

    def test_configured_but_unrepresented_sources_are_listed(self) -> None:
        """#207's core finding: 23 configured handles, 0 in the store."""
        records = [_rec(source_name="BillGertz"), _rec(author="lucidsci")]
        report = audit_records(
            records, configured_sources=["OpenAI", "timnitGebru", "BillGertz"]
        )
        assert report["configured_sources"]["unrepresented"] == ["OpenAI", "timnitGebru"]
        assert report["configured_sources"]["unrepresented_count"] == 2

    def test_a_check_that_did_not_run_is_not_an_all_clear(self) -> None:
        """'never checked' and 'checked, none missing' must not read the same.

        #207 is precisely a nominal stratum: a report that prints
        ``0 configured source(s) unrepresented`` when ``--configured-sources``
        was omitted would let the tool fake its own all-clear. The state must be
        explicit in the report and the summary.
        """
        unchecked = audit_records([_rec(source_name="X")])
        assert unchecked["configured_sources"]["checked"] is False
        summary = audit_summary(unchecked)
        assert "not run" in summary
        assert "0 configured source(s) unrepresented" not in summary

        checked = audit_records([_rec(source_name="X")], configured_sources=["X"])
        assert checked["configured_sources"]["checked"] is True
        assert "not run" not in audit_summary(checked)


class TestNoInventedVerdict:
    def test_the_report_has_no_threshold_keys(self) -> None:
        """The tool must not decide what 'too concentrated' means."""
        report = audit_records([_rec()])
        flat = repr(report).lower()
        for invented in ("is_concentrated", "too_concentrated", "is_unhealthy", "violation"):
            assert invented not in flat

    def test_empty_input_is_reported_not_crashed(self) -> None:
        report = audit_records([])
        assert report["total"] == 0
        assert report["concentration"]["top_n_share"] == 0.0
        assert len(report["by_platform"]["declared_but_empty"]) == len(
            report["by_platform"]["declared"]
        )


class TestSummaryAndCLI:
    def test_summary_is_one_line_and_names_the_numbers(self) -> None:
        records = [_rec(arena="elites", language=""), _rec(arena="")]
        summary = audit_summary(audit_records(records, top_n=3))
        assert "\n" not in summary
        assert "corpus audit" in summary
        assert "2 records" in summary

    def test_the_cli_exposes_the_command(self) -> None:
        from laclaugpt_data_collection.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            ["corpus-audit", "--records", "x.jsonl", "--top-n", "3",
             "--publication-floor", "2026-09-01"]
        )
        assert args.func.__name__ == "_corpus_audit"
        assert args.top_n == 3
        assert args.publication_floor == "2026-09-01"
