from datetime import datetime, timezone
from types import SimpleNamespace

from laclaugpt_data_collection.collectors.arxiv import map_paper
from laclaugpt_data_collection.collectors.documents import chunk_text
from laclaugpt_data_collection.collectors.mastodon import MastodonCollector, map_status
from laclaugpt_data_collection.collectors.spool import DirectorySpool
from laclaugpt_data_collection.collectors.telegram import map_message
from laclaugpt_data_collection.collectors.x_apify import map_apify_item
from laclaugpt_data_collection.collectors.youtube import map_video


def test_mastodon_mapping_and_collector_preserve_metadata():
    status = {
        "id": "42",
        "url": "https://social.example/@alice/42",
        "content": "<p>Hello <strong>world</strong></p>",
        "created_at": "2026-09-16T00:00:00Z",
        "language": "en",
        "account": {"acct": "alice", "display_name": "Alice", "url": "https://social.example/@alice"},
        "media_attachments": [{"type": "image", "url": "https://cdn.example/image.png"}],
        "favourites_count": 3,
        "reblogs_count": 2,
        "replies_count": 1,
    }
    record = map_status(status, instance_url="https://social.example")
    assert record is not None
    assert record.source_url == "https://social.example/@alice/42"
    assert record.text == "Hello world"
    assert record.engagement["reblogs_count"] == 2
    assert record.media_references[0].url == "https://cdn.example/image.png"

    class FakeMastodon:
        def timeline_hashtag(self, hashtag, limit):
            assert hashtag == "ai"
            assert limit == 5
            return [status]

    result = MastodonCollector("https://social.example", hashtag="#ai", limit=5, client=FakeMastodon()).collect()
    assert len(result.records) == 1
    assert result.raw_items_seen == 1


def test_telegram_mapping_uses_stable_channel_message_url():
    message = SimpleNamespace(
        id=7,
        raw_text="Synthetic Telegram text",
        text="Synthetic Telegram text",
        date=datetime(2026, 9, 16, tzinfo=timezone.utc),
        peer_id=SimpleNamespace(channel_id=123),
        media=object(),
    )
    record = map_message(message, channel_url="https://t.me/example")
    assert record is not None
    assert record.source_url == "https://t.me/example/7"
    assert record.provenance[0].metadata["channel_id"] == "123"
    assert record.media_references[0].metadata["download_required"] is True


def test_youtube_mapping_tracks_transcript_provenance():
    record = map_video(
        {"id": "abc", "title": "Demo", "description": "Description", "channel_id": "chan", "upload_date": "20260916", "duration": 10},
        transcript="Transcript text",
        transcript_source="youtube-transcript-api",
    )
    assert record is not None
    assert record.source_url == "https://www.youtube.com/watch?v=abc"
    assert record.text == "Transcript text"
    assert record.provenance[0].metadata["transcript_source"] == "youtube-transcript-api"


def test_arxiv_mapping_preserves_bibliography_and_pdf_reference():
    paper = SimpleNamespace(
        entry_id="https://arxiv.org/abs/2609.12345",
        title="Synthetic paper",
        summary="Abstract",
        published=datetime(2026, 9, 16, tzinfo=timezone.utc),
        updated=datetime(2026, 9, 16, tzinfo=timezone.utc),
        authors=[SimpleNamespace(name="A. Researcher")],
        categories=["cs.AI"],
        primary_category="cs.AI",
        pdf_url="https://arxiv.org/pdf/2609.12345",
    )
    record = map_paper(paper)
    assert record is not None
    assert record.source_url == "https://arxiv.org/abs/2609.12345"
    assert record.provenance[0].metadata["categories"] == ["cs.AI"]
    assert record.media_references[0].kind == "pdf"


def test_x_apify_mapping_is_canonical_and_keeps_raw_payload():
    item = {
        "id": "99",
        "url": "https://x.com/alice/status/99?utm_source=test",
        "text": "Synthetic post",
        "createdAt": "2026-09-16T00:00:00Z",
        "author": {"userName": "alice", "name": "Alice"},
        "likeCount": 12,
    }
    record = map_apify_item(item)
    assert record is not None
    assert record.source_url == "https://x.com/alice/status/99"
    assert record.engagement["like_count"] == 12
    assert record.provenance[0].metadata["raw_item"]["id"] == "99"


def test_document_chunking_and_spool_round_trip(tmp_path):
    chunks = chunk_text("Sentence one. Sentence two. Sentence three.", chunk_size=24, overlap=5)
    assert len(chunks) >= 2
    record = map_video({"id": "spool", "description": "hello"})
    assert record is not None
    spool = DirectorySpool(tmp_path)
    queued = spool.enqueue(record)
    assert queued.exists()
    summary, records = spool.process_all()
    assert summary.succeeded == 1
    assert records[0].source_url == record.source_url
    assert not queued.exists()
