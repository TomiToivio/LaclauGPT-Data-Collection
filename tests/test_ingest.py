from laclaugpt_data_collection.collectors.ingest import ingest_capture


def test_ingest_synthetic_tiktok_payload() -> None:
    payload = {
        "itemList": [
            {
                "id": "7400000000000000001",
                "desc": "Synthetic post #example",
                "createTime": "1789473600",
                "author": {"uniqueId": "synthetic_user", "nickname": "Synthetic User"},
                "stats": {"diggCount": 12, "commentCount": 3, "shareCount": 1, "playCount": 100},
                "video": {"playAddr": "https://media.example.invalid/video.mp4"},
                "textExtra": [{"hashtagName": "example"}],
            }
        ]
    }

    records = ingest_capture(
        response=payload,
        visited_url="https://www.tiktok.com/@synthetic_user",
        response_url="https://www.tiktok.com/api/post/item_list/",
        metadata={"capture_id": "synthetic-capture"},
        raw_ref="raw/tiktok/synthetic.json",
    )

    assert len(records) == 1
    record = records[0]
    assert record.document_id == "7400000000000000001"
    assert record.author == "synthetic_user"
    assert record.platform == "tiktok"
    assert record.collection_provenance.capture_id == "synthetic-capture"
