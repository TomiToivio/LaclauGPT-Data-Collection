from pathlib import Path

from laclaugpt_data_collection.models import NormalizedRecord
from laclaugpt_data_collection.storage.local import FilesystemObjectStore, SQLiteRecordStore


def test_sqlite_upsert_and_dedup_by_source_url(tmp_path: Path) -> None:
    store = SQLiteRecordStore(tmp_path / "state.sqlite3")
    first = NormalizedRecord(
        document_id="1",
        platform="synthetic",
        source_url="https://example.invalid/post/1?utm_source=test",
        text="first",
    )
    second = NormalizedRecord(
        document_id="legacy-other-id",
        platform="synthetic",
        source_url="https://EXAMPLE.invalid/post/1",
        text="updated",
    )

    store.upsert(first)
    store.upsert(second)

    assert store.contains("https://example.invalid/post/1")
    restored = store.get("https://example.invalid/post/1")
    assert restored is not None
    assert restored.source_url == "https://example.invalid/post/1"
    assert restored.content.text == "updated"

    output = tmp_path / "records.jsonl"
    store.export_jsonl(output)
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert '"source_url":"https://example.invalid/post/1"' in lines[0]


def test_filesystem_store_rejects_escape(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path / "objects")
    ref = store.put_text("raw/example.txt", "synthetic")
    assert ref == "raw/example.txt"
    assert (tmp_path / "objects/raw/example.txt").read_text(encoding="utf-8") == "synthetic"

    try:
        store.put_text("../escape.txt", "no")
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal must be rejected")
