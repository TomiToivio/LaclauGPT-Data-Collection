"""Regression tests for AI26 language annotation and collection wrapper diagnostics."""
from pathlib import Path
from types import SimpleNamespace

from laclaugpt_data_collection.collectors.rss import _entry_to_record
from laclaugpt_data_collection.language import resolve_language
from laclaugpt_data_collection.normalize import normalise


def test_declared_language_takes_precedence():
    assert resolve_language("short", declared="FI-fi") == ("fi", "source_metadata")


def test_undetermined_short_text_does_not_invent_language():
    assert resolve_language("OK") == ("", "insufficient_text")


def test_rss_language_from_feed():
    entry = SimpleNamespace(link="https://example.org/a", title="Otsikko", summary="Lyhyt", published="")
    record = _entry_to_record("https://example.org/feed", entry, feed_language="fi-FI")
    assert record is not None
    assert record.source.language == "fi"
    assert record.provenance[-1].metadata["language_method"] == "source_metadata"


def test_normaliser_preserves_non_x_language():
    record = normalise("instagram", {"id": "abc", "link": "https://example.org/a", "language": "pt"})
    assert record.source.language == "pt"


def test_laskin_wrapper_has_exit_marker_and_budget_flag():
    script = (Path(__file__).resolve().parents[1] / "scripts" / "run_ai26_laskin_collect.sh").read_text()
    assert "trap emit_end_marker EXIT" in script
    assert "--enforce-source-budgets" in script
    assert "exit \"$runner_status\"" in script
