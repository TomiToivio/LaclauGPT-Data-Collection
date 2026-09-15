from datetime import datetime, timezone

from laclaugpt_data_collection.browser import BrowserCapture, ingest_browser_capture
from laclaugpt_data_collection.storage.local import SQLiteRecordStore


def test_browser_capture_uses_existing_normalization_and_local_storage(tmp_path) -> None:
    capture = BrowserCapture(
        visited_url="https://www.tiktok.com/@synthetic_user",
        response_url="https://www.tiktok.com/api/post/item_list/",
        response={"itemList": [{"id": "7400000000000000002", "desc": "Synthetic browser post", "author": {"uniqueId": "synthetic_user"}}]},
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        capture_id="synthetic-browser-capture",
    )
    store = SQLiteRecordStore(tmp_path / "state.sqlite3")

    records = ingest_browser_capture(capture, store)

    assert len(records) == 1
    assert records[0].collection_provenance.capture_id == "synthetic-browser-capture"
    assert records[0].collection_provenance.visited_url == str(capture.visited_url)
    assert store.contains("tiktok", "7400000000000000002")
