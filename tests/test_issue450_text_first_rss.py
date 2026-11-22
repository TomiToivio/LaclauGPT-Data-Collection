"""#450: text-first collection -- a feed that ships the article body is full text.

The issue's complaint is that "a short RSS summary is not a complete article". The
collector already read `entry.content` (the publisher's full body) but used it only
for language detection and stored `title + summary` as the record text, so a feed
carrying whole articles was indistinguishable from one carrying teasers.

These tests pin the three states that must stay distinguishable: full body,
excerpt only, and a body the length cap truncated. A truncated record that does not
say it was truncated would be read as the complete article.
"""

from types import SimpleNamespace

from laclaugpt_data_collection.collectors.rss import MAX_FEED_TEXT_CHARS, _entry_to_record

BODY = "<p>" + ("The full article body sentence. " * 40) + "</p>"


def _entry(**overrides):
    entry = {
        "link": "https://example.org/article",
        "title": "A title",
        "summary": "A short teaser.",
        "published": "2026-11-20T10:00:00Z",
        "content": [],
    }
    entry.update(overrides)
    return SimpleNamespace(**entry)


def _meta(record):
    return record.provenance[-1].metadata


def test_feed_body_is_stored_as_the_record_text():
    record = _entry_to_record("https://example.org/feed", _entry(content=[{"value": BODY}]))
    assert record is not None
    assert "The full article body sentence." in record.text
    assert "<p>" not in record.text, "the body arrives as HTML and must become visible text"
    assert _meta(record)["text_source"] == "feed-content"
    assert _meta(record)["text_chars"] == len(record.text)
    assert _meta(record)["text_truncated"] is False
    assert "feed-content-to-text" in record.provenance[-1].transformations


def test_an_excerpt_only_feed_declares_itself_as_an_excerpt():
    record = _entry_to_record("https://example.org/feed", _entry())
    assert _meta(record)["text_source"] == "feed-excerpt"
    assert "A short teaser." in record.text


def test_a_body_over_the_cap_is_truncated_and_says_so():
    huge = "x" * (MAX_FEED_TEXT_CHARS + 500)
    record = _entry_to_record("https://example.org/feed", _entry(content=[{"value": huge}]))
    assert len(record.text) == MAX_FEED_TEXT_CHARS
    assert _meta(record)["text_truncated"] is True
    assert _meta(record)["text_chars"] == MAX_FEED_TEXT_CHARS


def test_the_shorter_form_still_wins_when_the_body_is_a_stub():
    """A feed that ships only a placeholder body must not lose the real summary."""
    record = _entry_to_record(
        "https://example.org/feed", _entry(content=[{"value": "<p>.</p>"}])
    )
    assert _meta(record)["text_source"] == "feed-excerpt"
    assert "A short teaser." in record.text
