from __future__ import annotations

from pathlib import Path

from laclaugpt_data_collection.extraction.html import extract_visible_text


def test_phase1_fixture_has_dependency_free_text_provenance() -> None:
    fixture = Path(__file__).parent / "fixtures" / "phase1_article.html"
    result = extract_visible_text(fixture.read_text(encoding="utf-8"))

    assert "Synthetic Research Note" in result.text
    assert "public-safe synthetic collection text" in result.text
    assert "window.secret" not in result.text
    assert result.extractor == "stdlib-html.parser"
    assert result.extractor_version is None


def test_phase1_package_is_not_imported_by_top_level_package() -> None:
    import sys
    import laclaugpt_data_collection

    assert laclaugpt_data_collection is not None
    assert "laclaugpt_data_collection.extraction.metadata" not in sys.modules
