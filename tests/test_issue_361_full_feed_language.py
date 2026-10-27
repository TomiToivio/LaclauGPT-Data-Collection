"""Regressions for issue #361: full feed text used for language classification."""
from __future__ import annotations

import sys
import types

from laclaugpt_data_collection.collectors.rss import _entry_to_record


def test_full_feed_content_drives_detection(monkeypatch):
    observed = []
    fake = types.ModuleType("laclaugpt_data_collection.language")
    def resolver(text, *, declared=""):
        observed.append((text, declared))
        return ("en", "detected_langdetect")
    fake.resolve_language = resolver
    monkeypatch.setitem(sys.modules, "laclaugpt_data_collection.language", fake)
    entry = types.SimpleNamespace(
        link="https://example.org/article", title="Brief", summary="Short",
        content=[{"value": "Long body " * 200}], published="2026-10-26",
    )
    record = _entry_to_record("https://example.org/feed", entry)
    assert record is not None
    assert record.source.language == "en"
    assert len(observed[0][0]) > 1000
    assert record.content.text == "Brief\n\nShort"


def test_source_language_is_preserved(monkeypatch):
    seen = []
    fake = types.ModuleType("laclaugpt_data_collection.language")
    def resolver(text, *, declared=""):
        seen.append(declared)
        return ("fi", "source_metadata")
    fake.resolve_language = resolver
    monkeypatch.setitem(sys.modules, "laclaugpt_data_collection.language", fake)
    entry = types.SimpleNamespace(
        link="https://example.org/a", title="Short", summary="",
        content=[{"value": "English content " * 100}], published="",
    )
    record = _entry_to_record("https://example.org/feed", entry, feed_language="fi")
    assert record is not None
    assert seen == ["fi"]
    assert record.source.language == "fi"
