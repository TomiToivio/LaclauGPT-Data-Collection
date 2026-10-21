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


class TestTheDecisionRecord:
    def test_the_brief_records_both_decisions_as_resolved(self) -> None:
        text = _brief()
        assert "Status: resolved" in text.replace("*", "")
        assert "**D1" in text and "**D2" in text
        assert "how they were resolved" in text

    def test_the_headline_only_cost_is_stated(self) -> None:
        """The marker does not turn a headline into a council decision."""
        assert "headline-plus-timestamp" in _brief()

    def test_all_four_options_are_enumerated(self) -> None:
        text = _brief()
        for marker in (
            "1. Municipal documents",
            "2. State / utility-commission layer",
            "3. News-discovery layer",
            "4. Out of scope",
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

    def test_the_aggregator_row_declares_its_identity(self) -> None:
        """A row whose items link at an aggregator must say so, not be guessed."""
        rows = self._aggregator_rows()
        assert rows, "the tracked plan carries the Google News discovery stratum"
        for row in rows:
            assert row.get("source_identity") == "aggregator", row.get("name")
            assert row.get("aggregator") == "google_news", row.get("name")

    def test_a_publisher_feed_carries_no_aggregator_declaration(self) -> None:
        for row in _manifest().get("feed", []):
            if "news.google.com" in str(row.get("feed_url", "")):
                continue
            assert not row.get("source_identity"), (
                f"{row.get('name')} is a publisher feed; the marker must stay meaningful"
            )


class TestAggregatorRecordsCarryPublisherProvenance:
    """The marker is only useful if the publisher travels with the record."""

    FEED = "https://news.google.com/rss/search?q=x"
    ENTRY = {
        "link": "https://news.google.com/rss/articles/CBMiAFBVV95",
        "title": "Memphis fails to pass 1-year data center moratorium",
        "summary": "",
        "published": "Wed, 21 Oct 2026 03:48:00 GMT",
        "source": {"href": "https://www.cbsnews.com", "title": "CBS News"},
    }

    def _record(self, **overrides):
        from types import SimpleNamespace

        from laclaugpt_data_collection.collectors.rss import _entry_to_record

        record = _entry_to_record(
            self.FEED, SimpleNamespace(**{**self.ENTRY, **overrides})
        )
        assert record is not None
        return record

    def test_the_entry_publisher_is_recorded(self) -> None:
        record = self._record()
        metadata = record.provenance[-1].metadata
        assert record.source_url == "https://news.google.com/rss/articles/CBMiAFBVV95"
        assert metadata["publisher_url"] == "https://www.cbsnews.com"
        assert metadata["publisher_name"] == "CBS News"

    def test_a_plain_feed_entry_records_no_publisher(self) -> None:
        metadata = self._record(source=None).provenance[-1].metadata
        assert "publisher_url" not in metadata and "publisher_name" not in metadata

    def test_the_declaration_stamps_identity_provider_and_publisher(self) -> None:
        from laclaugpt_data_collection import server_runner

        stamped = server_runner._stamp_source_metadata(
            self._record(),
            {
                "name": "local_data_centre_moratorium_news",
                "feed_url": self.FEED,
                "source_identity": "aggregator",
                "aggregator": "google_news",
            },
            collection_id="ai26",
            worker_id="test",
        )
        raw = stamped.source.raw_metadata
        assert raw["source_identity"] == "aggregator"
        assert raw["aggregator"] == {
            "provider": "google_news",
            "publisher_url": "https://www.cbsnews.com",
            "publisher_name": "CBS News",
        }

    def test_a_publisher_row_stamps_no_aggregator_block(self) -> None:
        from laclaugpt_data_collection import server_runner

        stamped = server_runner._stamp_source_metadata(
            self._record(source=None),
            {"name": "guardian_ai", "feed_url": "https://example.invalid/feed"},
            collection_id="ai26",
            worker_id="test",
        )
        assert "source_identity" not in stamped.source.raw_metadata
        assert "aggregator" not in stamped.source.raw_metadata

    def test_the_laskin_stamper_stamps_the_same_contract(self) -> None:
        from laclaugpt_data_collection import ai26_laskin_runner as laskin

        stamped = laskin._stamp(
            self._record(),
            {
                "name": "local_data_centre_moratorium_news",
                "kind": "web_source",
                "source_identity": "aggregator",
                "aggregator": "google_news",
            },
            collection_id="ai26",
            worker_id="test",
        )
        raw = stamped.source.raw_metadata
        assert raw["source_identity"] == "aggregator"
        assert raw["aggregator"]["publisher_name"] == "CBS News"
