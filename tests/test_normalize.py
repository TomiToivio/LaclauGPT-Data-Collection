from laclaugpt_data_collection.normalize import normalise


def test_normalise_tiktok_synthetic_record() -> None:
    raw_item = {
        "id": "7400000000000000001",
        "desc": "Exact synthetic platform item",
        "stats": {"diggCount": 12},
    }
    record = normalise(
        "tiktok",
        {
            "id": "7400000000000000001",
            "author": "synthetic_user",
            "timestamp": "2026-09-15T12:00:00Z",
            "tiktok_url": "https://www.tiktok.com/@synthetic_user/video/7400000000000000001",
            "body": "Synthetic caption",
            "hashtags": "synthetic,example",
            "likes": 12,
            "video_url": "https://media.example.invalid/video.mp4",
        },
        metadata={"capture_id": "capture-test", "run_id": "run-test"},
        raw_ref="raw/tiktok/test.json",
        raw_payload=raw_item,
    )

    assert record.schema_version == "1.1.0"
    assert record.document_id == "7400000000000000001"
    assert record.platform == "tiktok"
    assert record.hashtags == ["synthetic", "example"]
    assert record.engagement["likes"] == 12
    assert record.raw_ref == "raw/tiktok/test.json"
    assert record.raw_capture.payload == raw_item
    assert record.raw_capture.preserved is True
    assert record.human_readable.summary == "Synthetic caption"
    assert record.collection_provenance.capture_id == "capture-test"
