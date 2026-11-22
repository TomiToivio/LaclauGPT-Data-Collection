"""#450: a feed excerpt is not a complete article, and the record must say which it holds.

The owner decision is text-first collection. The collector already parsed the publisher's own
``entry.content`` — but used it only for language detection and stored ``title + summary``, i.e. it kept the
excerpt it had a full text for. These tests pin the stored text and the provenance that labels it.
"""
from __future__ import annotations

from types import SimpleNamespace

from laclaugpt_data_collection.collectors.rss import _entry_to_record

BODY = "This is the full article body. " * 40


def _entry(**fields) -> SimpleNamespace:
    base = {"link": "https://example.invalid/post", "title": "A post", "summary": "Short summary.",
            "published": "2026-05-01T10:00:00Z", "id": "post-1", "author": "Author"}
    base.update(fields)
    return SimpleNamespace(**base)


def test_publisher_full_content_is_stored_rather_than_the_excerpt():
    record = _entry_to_record("https://example.invalid/feed", _entry(content=[{"value": BODY}]))
    assert BODY.strip() in record.text
    assert record.collection_provenance.metadata["text_completeness"] == "full_text"
    assert record.collection_provenance.metadata["text_source"] == "feed_entry_content"
    assert record.collection_provenance.metadata["text_chars"] == len(record.text)


def test_an_entry_with_only_a_summary_is_labelled_as_an_excerpt():
    record = _entry_to_record("https://example.invalid/feed", _entry())
    assert record.text.strip() == "A post\n\nShort summary."
    assert record.collection_provenance.metadata["text_completeness"] == "feed_excerpt"
    assert record.collection_provenance.metadata["text_source"] == "feed_entry_summary"


def test_a_shorter_content_block_does_not_beat_a_richer_excerpt():
    """Some feeds put a teaser in `content` and the real summary elsewhere; never store the shorter one."""
    record = _entry_to_record(
        "https://example.invalid/feed",
        _entry(summary="A much longer summary that carries the argument of the piece." * 3,
               content=[{"value": "teaser"}]),
    )
    assert record.collection_provenance.metadata["text_completeness"] == "feed_excerpt"
    assert "teaser" not in record.text
