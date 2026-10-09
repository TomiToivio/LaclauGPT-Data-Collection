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
        assert "configured-source check not run" in summary
        assert "0 configured source(s) unrepresented" not in summary

        checked = audit_records([_rec(source_name="X")], configured_sources=["X"])
        assert checked["configured_sources"]["checked"] is True
        # Pin the CLAUSE, not the substring "not run": since #207 the summary also
        # carries a stage-reachability clause that can legitimately say "not run".
        assert "configured-source check not run" not in audit_summary(checked)


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


class TestStageReachability:
    """#207: a stage-deferred platform must not read as a coverage failure.

    The X stratum is nominal on Laskin because the stage is browser-free by
    design. Counting `x` as "declared but empty" alongside a real gap makes the
    nominal stratum look like a problem to fix here, and hides the one platform
    that genuinely lacks a collector.
    """

    def test_deferred_and_empty_platforms_are_separated_from_expected_gaps(self) -> None:
        records = [_rec(platform="rss"), _rec(platform="x")]
        report = audit_records(
            records, deferred_platforms=["x", "youtube", "tiktok", "instagram"]
        )
        bp = report["by_platform"]
        assert set(bp["empty_and_deferred"]) == {"youtube", "tiktok", "instagram"}
        assert "mastodon" in bp["empty_and_expected"], "a reachable platform still counts as a gap"
        assert bp["deferred_check_ran"] is True

    def test_a_deferred_platform_that_has_records_is_flagged(self) -> None:
        """The #207 contradiction: `x` is declared deferred AND has 55 records.

        Either the declaration is stale or the records are a historical artefact;
        the tool must name it rather than silently pick one.
        """
        report = audit_records([_rec(platform="x")], deferred_platforms=["x"])
        assert report["by_platform"]["deferred_but_has_records"] == ["x"]

    def test_without_the_deferral_list_the_old_behaviour_is_preserved(self) -> None:
        """Omitting the list must not silently invent an all-clear."""
        report = audit_records([_rec(platform="rss")])
        bp = report["by_platform"]
        assert bp["deferred_check_ran"] is False
        for platform in ("youtube", "mastodon", "tiktok", "instagram"):
            assert platform in bp["declared_but_empty"]

    def test_summary_distinguishes_the_three_states(self) -> None:
        records = [_rec(platform="rss"), _rec(platform="x")]
        with_deferral = audit_summary(
            audit_records(records, deferred_platforms=["x", "youtube", "tiktok", "instagram"])
        )
        without = audit_summary(audit_records(records))
        assert "deferred by stage" in with_deferral
        assert "stage-reachability check not run" in without, (
            "an unrun check must say so, not read as zero gaps"
        )


class TestStudyConfigDeclaresReachability:
    """The declaration must live in the tracked public study config (#207)."""

    def test_the_ai26_study_declares_stage_reachability(self) -> None:
        from pathlib import Path

        import yaml

        path = (
            Path(__file__).resolve().parents[1] / "configs" / "studies" / "ai26.example.yaml"
        )
        study = yaml.safe_load(path.read_text(encoding="utf-8"))
        stages = study.get("stage_reachability")
        assert stages, "the study config must declare per-stage reachability"
        laskin = stages.get("laskin_non_browser")
        assert laskin, "the browser-free server stage must declare what it can reach"
        assert "x" in laskin["deferred"], "X is browser-only by design on Laskin"
        assert "rss" in laskin["reachable"]
        assert laskin.get("rationale"), "a deferral must say why"

    def test_the_declaration_covers_every_declared_platform(self) -> None:
        """An platform in neither list is an unstated assumption."""
        from pathlib import Path

        import yaml

        path = (
            Path(__file__).resolve().parents[1] / "configs" / "studies" / "ai26.example.yaml"
        )
        study = yaml.safe_load(path.read_text(encoding="utf-8"))
        enabled = {
            name for name, cfg in (study.get("platforms") or {}).items()
            if isinstance(cfg, dict) and cfg.get("enabled")
        }
        declared = set()
        for stage in (study.get("stage_reachability") or {}).values():
            if isinstance(stage, dict):
                declared |= set(stage.get("reachable") or [])
                declared |= set(stage.get("deferred") or [])
        # `scholarly` is the study-level name for the arxiv collector.
        missing = enabled - declared - {"scholarly"}
        assert not missing, f"platforms with no reachability statement: {sorted(missing)}"
