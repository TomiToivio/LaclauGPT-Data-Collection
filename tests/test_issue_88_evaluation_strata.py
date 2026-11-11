"""The stratification audit must measure the frame, not the store (#88).

The number this file protects is the denominator. §4.2 needs an evaluation sample drawn from
documents that are *ready and inside the declared window*; the store holds ~5,000 more published
before the window that can never be sampled. An audit that counts those inflates every cell and
turns an empty stratum into a full one.

The other property is honesty about missingness: a document with no stored analysis is **uncoded**,
not "non-populist". If silence were counted as a negative finding, the abstention stratum §4.2 asks
for would be invisible and the coverage gap would look like agreement.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "audit_evaluation_strata_88.py"
spec = importlib.util.spec_from_file_location("audit_evaluation_strata_88", SCRIPT)
assert spec and spec.loader
audit = importlib.util.module_from_spec(spec)
# Register before executing: the module defines dataclasses, and dataclasses resolves annotations
# through sys.modules[cls.__module__].
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)


def document(url: str, *, arena: str, language: str, platform: str = "rss", published: str = "2026-10-01T00:00:00+00:00", source_name: str = "feed", country: str = "fi"):
    return {
        "source_url": url,
        "arena": arena,
        "country": country,
        "handoff": {"published_at": published, "status": "ready"},
        "source": {
            "language": language,
            "platform": platform,
            "country": country,
            "raw_metadata": {"arena": "", "source_name": source_name},
        },
    }


def populist(coding: bool = True, *, uncertain: bool = False, abstained: bool = False) -> dict:
    analysis = {"formula_of_populism": {}}
    if coding:
        analysis["formula_of_populism"] = {
            "collective_subject": "the people",
            "antagonistic_frontier": "the elite",
        }
    else:
        analysis["formula_of_populism"] = {"non_populist_reason": "no frontier"}
    analysis["uncertainty"] = ["stance unclear"] if uncertain else []
    analysis["abstentions"] = ["no coding"] if abstained else []
    return analysis


def test_silence_is_uncoded_not_a_negative_finding():
    assert audit.formation_of(None) == audit.FORMATION_UNCODED
    assert audit.formation_of({}) == audit.FORMATION_UNCODED
    assert audit.formation_of({"formula_of_populism": {}}) == audit.FORMATION_UNCODED
    assert audit.formation_of(populist(True)) == audit.FORMATION_POPULIST
    assert audit.formation_of(populist(False)) == audit.FORMATION_NON_POPULIST


def test_the_proxy_reads_the_stored_formula_rather_than_a_second_model():
    analysis = populist(True)
    assert audit.formation_of(analysis) == audit.FORMATION_POPULIST
    # the reason field alone is non-populist evidence, never populist
    assert audit.formation_of({"formula_of_populism": {"non_populist_reason": "x"}}) == audit.FORMATION_NON_POPULIST


def test_arena_and_language_come_from_the_record_even_when_raw_metadata_is_blank():
    rows = audit.rows_from_documents([document("a", arena="elites", language="EN")])
    assert rows[0].arena == "elites"
    assert rows[0].language == "en", "language tags are compared case-folded"
    assert rows[0].platform == "rss"


def test_a_record_without_an_arena_is_unassigned_rather_than_dropped():
    rows = audit.rows_from_documents([document("a", arena="", language="en")])
    assert rows[0].arena == audit.UNASSIGNED
    report = audit.build_report(rows)
    assert report["arena"]["unassigned"] == 1
    assert report["arena"]["unassigned_share"] == pytest.approx(1.0)


def test_min_cell_table_reports_coverage_instead_of_a_verdict():
    rows = audit.rows_from_documents(
        [document(f"e{i}", arena="elites", language="en") for i in range(30)]
        + [document(f"f{i}", arena="grassroots", language="fi") for i in range(4)]
    )
    analyses = {row.published_at: None for row in rows}  # unused, keeps the fixture honest
    table = audit.min_cell_feasibility(rows, thresholds=(5, 10, 30))
    by_threshold = {row["min_cell"]: row for row in table}

    assert by_threshold[5]["cells_at_or_above"] == 1
    assert by_threshold[5]["documents_in_cells_at_or_above"] == 30
    assert by_threshold[5]["share_of_frame"] == pytest.approx(30 / 34)
    assert by_threshold[30]["cells_at_or_above"] == 1
    assert by_threshold[10]["cells_below"][0]["n"] == 4
    assert analyses  # the dict exists; no analysis is needed to count cells


def test_finnish_cells_are_reported_per_arena_and_per_platform():
    rows = audit.rows_from_documents(
        [
            document("f1", arena="elites", language="fi", platform="x"),
            document("f2", arena="elites", language="fi", platform="x"),
            document("f3", arena="parliamentary", language="fi", platform="rss"),
            document("e1", arena="elites", language="en"),
        ]
    )
    language = audit.language_profile(rows)
    assert language["finnish_total"] == 3
    assert language["finnish_by_arena"] == {"elites": 2, "parliamentary": 1}
    assert language["finnish_by_arena_platform"]["elites/x"] == 2
    assert language["en_elites"]["documents"] == 1


def test_option_four_counts_the_coded_english_elite_cell():
    rows = audit.rows_from_documents(
        [
            document("e1", arena="elites", language="en"),
            document("e2", arena="elites", language="en"),
            document("f1", arena="elites", language="fi"),
        ],
        {"e1": populist(True), "e2": populist(False)},
    )
    report = audit.build_report(rows)
    option_four = report["option_checks"]["option_4_restrict_to_en_elites"]
    assert option_four["documents"] == 2, "the sample is drawn from documents, coded or not"
    assert option_four["coded_documents"] == 2, "agreement needs a model output to compare against"
    assert option_four["uncoded_documents"] == 0


def test_the_report_counts_uncertainty_abstention_and_uncoded_separately():
    documents = [
        document("a", arena="elites", language="en"),
        document("b", arena="elites", language="en"),
        document("c", arena="grassroots", language="fi"),
    ]
    analyses = {
        "a": populist(True, uncertain=True),
        "b": populist(False, abstained=True),
        # c has no stored analysis at all
    }
    report = audit.build_report(audit.rows_from_documents(documents, analyses))
    assert report["uncertainty"] == {"uncertain": 1, "abstained": 1, "uncoded": 1}


def test_inflow_uses_the_frames_own_span_not_a_calendar_guess():
    rows = audit.rows_from_documents(
        [
            document("a", arena="elites", language="en", published="2026-09-01T00:00:00+00:00"),
            document("b", arena="elites", language="en", published="2026-09-08T00:00:00+00:00"),
        ]
    )
    inflow = audit.weekly_inflow(rows)
    assert inflow["elites"]["documents"] == 2
    assert inflow["elites"]["per_week"] == pytest.approx(2.0, rel=0.2)


def test_markdown_names_the_frame_and_the_four_options(tmp_path: Path):
    rows = audit.rows_from_documents([document("a", arena="elites", language="en")], {"a": populist(True)})
    report = audit.build_report(rows)
    text = audit.render_markdown(report)
    assert "handoff.status=ready" in text
    for marker in ("Minimum cell size (option 1)", "demote Finnish", "extend or add sources", "en × elites"):
        assert marker in text
    out = tmp_path / "audit.json"
    out.write_text(json.dumps(report), encoding="utf-8")
    assert json.loads(out.read_text())["schema_version"] == "ai26.evaluation_strata/1"


def test_the_loader_reads_the_ready_frame_only(monkeypatch):
    seen = {}

    class FakeCursor(list):
        def limit(self, count):
            seen["limit"] = count
            return self

    class FakeCollection:
        def __init__(self, name):
            self.name = name

        def find(self, query, projection=None):
            seen[f"query_{self.name}"] = query
            if self.name == "ai26__records":
                return FakeCursor([document("a", arena="elites", language="en")])
            return FakeCursor(
                [{"source_url": "a", "result": {"analysis": populist(True)}}]
            )

    class FakeDB:
        def __getitem__(self, name):
            return FakeCollection(name)

    class FakeClient:
        def __init__(self, uri):
            seen["uri_set"] = bool(uri)

        def __getitem__(self, name):
            return FakeDB()

        def close(self):
            pass

    monkeypatch.setattr("pymongo.MongoClient", FakeClient)
    rows = audit.load_rows_from_mongo(uri="mongodb://x", database="db")

    assert rows and rows[0].formation == audit.FORMATION_POPULIST
    query = seen["query_ai26__records"]
    assert query["handoff.status"] == "ready"
    assert "handoff.published_at" in query, "the window is part of the frame, not a filter applied later"
    assert query["project_id"] == "ai26"
