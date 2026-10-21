"""Issue #296 -- the local data-centre stratum decisions must stay visible.

No stratum can be chosen by an agent: it needs an inclusion rule the owner sets.
What this test pins is (a) the mechanism the brief claims exists -- a browser-free
`web_source` row really is collected as a document -- and (b) that the *open
decision* cannot go quiet, including the aggregator row PR #299 added to the
manifest before that decision was taken.

If a decision is taken later, update the brief, the manifest and this test in the
same commit. That is the point: the state of an owner-gated decision should fail
CI, not live in a chat transcript.
"""
from __future__ import annotations

import inspect
import tomllib
from pathlib import Path

from laclaugpt_data_collection import ai26_laskin_runner as runner

REPO = Path(__file__).resolve().parents[1]
BRIEF = REPO / "docs" / "AI26_LOCAL_DATACENTRE_STRATUM.md"
MANIFEST = REPO / "configs" / "studies" / "ai26.sources.example.toml"
AGGREGATOR_ROW = "local_data_centre_moratorium_news"


def _manifest() -> dict:
    return tomllib.loads(MANIFEST.read_text(encoding="utf-8"))


def _brief() -> str:
    return BRIEF.read_text(encoding="utf-8")


class TestTheMechanismExists:
    def test_web_source_runs_on_the_browser_free_stage(self) -> None:
        assert "web_source" in runner._NON_BROWSER_TABLES

    def test_a_web_source_row_is_fetched_as_a_document(self) -> None:
        source = inspect.getsource(runner._records_for_job)
        assert 'kind == "web_source"' in source
        assert "fetch_web_child" in source

    def test_web_source_rows_are_declared_with_a_url(self) -> None:
        """The brief's proposed row shape must match what the loader reads."""
        rows = _manifest().get("web_source", [])
        assert rows, "the manifest still needs at least one web_source row"
        for row in rows:
            assert str(row.get("url") or row.get("homepage") or "").startswith("http")


class TestTheOpenDecisionsStayVisible:
    def test_the_brief_is_not_marked_decided(self) -> None:
        text = _brief().replace("*", "")
        assert "Status: two decisions pending" in text

    def test_both_open_decisions_are_named(self) -> None:
        text = _brief()
        assert "**D1" in text and "aggregator" in text
        assert "**D2" in text

    def test_all_four_options_are_enumerated(self) -> None:
        text = _brief()
        for marker in (
            "1. Municipal documents",
            "2. State / utility-commission layer",
            "3. News-query layer",
            "4. Declare out of scope",
        ):
            assert marker in text, marker

    def test_the_probe_evidence_names_the_blockers(self) -> None:
        text = _brief()
        for endpoint in ("Virginia SCC", "CPUC", "Florida PSC"):
            assert endpoint in text, endpoint
        assert "403" in text and "404" in text


class TestTheAggregatorRowAndItsCaveatTravelTogether:
    """PR #299 added a Google News row; the contract caveat must not get lost."""

    def _aggregator_rows(self) -> list[dict]:
        return [
            row
            for row in _manifest().get("feed", [])
            if "news.google.com" in str(row.get("feed_url", ""))
        ]

    def test_the_aggregator_row_is_still_declared_active_or_not(self) -> None:
        rows = self._aggregator_rows()
        if not rows:
            return  # removed by the owner: D1 is then simply answered "no"
        names = {str(row.get("name")) for row in rows}
        assert AGGREGATOR_ROW in names, (
            "the brief documents the row added by PR #299 by name; keep them in sync"
        )

    def test_an_aggregator_row_cannot_exist_without_the_documented_caveat(self) -> None:
        if not self._aggregator_rows():
            return
        text = _brief()
        assert "news.google.com/rss/articles" in text, (
            "an aggregator feed is configured, so the brief must state that its "
            "records' source_url is the aggregator, not the publisher"
        )
        assert "headline" in text.lower(), (
            "and that the payload is a headline, not article text"
        )

    def test_no_code_claims_to_resolve_aggregator_identity(self) -> None:
        """D1 is unanswered: nothing may silently pretend the identity is fixed."""
        source = inspect.getsource(runner._records_for_job)
        assert "source_identity" not in source, (
            "the loader grew an aggregator-identity implementation; update the "
            "brief's D1 from 'open' to 'decided' and pin the new contract here"
        )
