"""Regression coverage for #457 runtime risk and #459 language abstention."""
from __future__ import annotations

from laclaugpt_data_collection.collectors.mastodon import map_status
from laclaugpt_data_collection.collectors.bluesky import _map_post
from laclaugpt_data_collection.language import stamp_language_status


def test_mastodon_platform_language_is_source_metadata():
    record = map_status(
        {"id": "42", "url": "https://social.example/@researcher/42",
         "content": "<p>Hi</p>", "language": "en"},
        instance_url="https://social.example",
    )
    assert record is not None
    assert record.source.language == "en"
    assert record.provenance[-1].metadata["language_method"] == "source_metadata"


def test_mastodon_short_post_without_platform_tag_abstains():
    record = map_status(
        {"id": "43", "url": "https://social.example/@researcher/43",
         "content": "<p>OK</p>", "language": None},
        instance_url="https://social.example",
    )
    assert record is not None
    stamp_language_status(record)
    assert record.source.language == ""
    assert record.source.raw_metadata["language_status"] == "undetermined"
    assert record.source.raw_metadata["language_reason"] == "insufficient_text"


def test_bluesky_short_post_with_platform_tag_remains_determined():
    record = _map_post({
        "uri": "at://did:plc:example/app.bsky.feed.post/test",
        "record": {"text": "Hei", "langs": ["fi"]},
        "author": {"handle": "someone.example"},
    })
    assert record is not None
    stamp_language_status(record)
    assert record.source.raw_metadata["language_status"] == "determined"
    assert record.source.raw_metadata["language_provenance"] == "platform_or_feed_metadata"
