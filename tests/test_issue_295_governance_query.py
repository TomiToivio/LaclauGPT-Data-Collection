# -*- coding: utf-8 -*-
"""Issue #295: the `ai_governance` query is now a measured, precision-preserving one.

The old query — ``all:artificial intelligence AND (governance OR regulation OR
audit OR evaluation OR liability OR standards)`` — matched ``evaluation``/``audit``
in essentially every ML abstract and filled 40% of the parliamentary arena with
technical papers. The decision taken on 2026-10-21 is option 1 of the issue:
governance terms required in the *title*.

This module pins three things:

1. the tracked config sends that query, and no longer sends the firehose terms;
2. the query is sent to arXiv **as written**. `ArxivCollector` used to prefix
   `all:` unconditionally, which turns any field-qualified query into
   ``all:all:(ti:...)``; the API answers HTTP 400, so a precision query would have
   collected nothing at all (measured: 400 for `all:all:(...)`, 336 for the same
   query without the doubled prefix);
3. a category restriction (`cat:cs.CY`, option 2) is not silently smuggled into a
   query string, where the collector's `all:` prefix would demote it to a text
   term — measured 247,964 results with the prefix versus 2,592 without.

The measured comparison and the wording of the judgement live in
``docs/ai26-sampling-decision-295-governance-query.md``; a config test asserts the numbers
stay there with the decision.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from laclaugpt_data_collection.collectors.arxiv import ArxivCollector

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "configs" / "studies" / "ai26.sources.example.toml"
DECISIONS = REPO / "docs" / "ai26-sampling-decision-295-governance-query.md"

GOVERNANCE_TERMS = (
    "AI governance",
    "AI regulation",
    "AI Act",
    "algorithmic accountability",
    "AI audit",
)


def manifest() -> dict:
    return tomllib.loads(MANIFEST.read_text(encoding="utf-8"))


def governance_row() -> dict:
    return next(row for row in manifest()["scholarly_query"] if row["name"] == "ai_governance")


class TestTheTrackedQuery:
    def test_the_source_keeps_its_sampling_role(self) -> None:
        row = governance_row()
        assert row["arena"] == "parliamentary", "the stratum's arena is unchanged"
        assert row["priority"] == "P1"
        assert "arxiv" in row["services"]
        assert row.get("active", True) is not False

    def test_governance_terms_are_required_in_the_title(self) -> None:
        query = governance_row()["query"]
        for term in GOVERNANCE_TERMS:
            assert f'ti:"{term}"' in query, f"{term} must be a title-field requirement"

    def test_the_firehose_terms_are_gone(self) -> None:
        query = governance_row()["query"].lower()
        assert "evaluation" not in query, (
            "`evaluation` occurs in nearly every ML abstract; it is what made the "
            "query a firehose"
        )
        assert not re.search(r"\bor\s+audit\b", query), (
            "a bare `audit` OR-term is the second firehose term"
        )
        assert not query.startswith("all:artificial"), "the old all-field query must not return"

    def test_a_category_clause_is_not_put_in_the_query_string(self) -> None:
        """`cat:` in the query text is neutered by the collector's `all:` prefix."""
        query = governance_row()["query"]
        assert "cat:" not in query, (
            "a category restriction belongs in `categories=`, not in the query string: "
            "with the `all:` prefix it is read as text (measured 247,964 vs 2,592 results)"
        )

    def test_the_query_is_field_qualified_so_it_is_not_prefixed(self) -> None:
        query = governance_row()["query"]
        assert query.lstrip().startswith("(ti:") or query.lstrip().startswith("ti:"), (
            "the query must declare its field, or the collector prefixes all: to it"
        )


class TestTheQueryIsActuallySent:
    """A precision query that the API rejects with 400 preserves nothing."""

    def test_the_configured_query_is_sent_unchanged(self) -> None:
        query = governance_row()["query"]
        assert ArxivCollector(query, max_results=5)._query() == query

    def test_a_plain_query_still_gets_the_all_field_prefix(self) -> None:
        assert (
            ArxivCollector("artificial intelligence AND governance")._query()
            == "all:artificial intelligence AND governance"
        )

    def test_a_field_qualified_query_is_never_double_prefixed(self) -> None:
        sent = ArxivCollector('(ti:"AI governance" OR ti:"AI Act")')._query()
        assert not sent.startswith("all:all:"), "all:all:(...) is an HTTP 400, not a search"
        assert sent == '(ti:"AI governance" OR ti:"AI Act")'

    def test_a_category_restriction_is_appended_once(self) -> None:
        sent = ArxivCollector('ti:"AI governance"', categories=["cs.CY"])._query()
        assert sent == 'ti:"AI governance" AND (cat:cs.CY)'

    @pytest.mark.parametrize(
        "query",
        [
            'abs:"algorithmic accountability"',
            'au:Zuboff AND ti:surveillance',
            'cat:cs.CY AND ti:governance',
            'primary_category:cs.CY',
        ],
    )
    def test_every_declared_field_is_left_as_written(self, query: str) -> None:
        assert ArxivCollector(query)._query() == query


def test_the_decision_and_its_measurements_are_recorded() -> None:
    """A sampling decision must carry the measurement that produced it."""
    text = DECISIONS.read_text(encoding="utf-8")
    assert "#295" in text
    assert "option 1" in text.casefold()
    for measured in ("254,783", "249,905", "2,592", "336", "129"):
        assert measured in text, f"the recorded decision is missing the measurement {measured}"
    assert "0/60" in text, "the precision sample of the old query must be recorded"
