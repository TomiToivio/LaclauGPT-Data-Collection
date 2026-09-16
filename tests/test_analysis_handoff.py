import json
from pathlib import Path

from laclaugpt_data_collection.handoff import build_handoff, source_revision
from laclaugpt_data_collection.handoff_runner import export_handoffs
from laclaugpt_data_collection.store import CollectionStore


def record(
    source_url: str,
    *,
    collection_id: str = "brazil26",
    published: str = "2026-09-16T10:00:00Z",
    media: bool = False,
) -> dict:
    refs = []
    if media:
        refs = [{"kind": "image", "url": "https://media.example/image.jpg", "media_index": 0}]
    return {
        "collection_id": collection_id,
        "source_url": source_url,
        "source": {"platform": "x", "created_at": published, "raw_metadata": {}},
        "content": {"text": "synthetic source text", "media_references": refs},
        "provenance": [{"metadata": {"collection_id": collection_id}}],
    }


def write_record(root: Path, value: dict) -> None:
    path = root / "normalized" / "x.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value) + "\n")


def test_handoff_key_and_revision_are_stable() -> None:
    value = record("https://example.org/post/1")
    first = build_handoff(value, project_id="shared", run_id="run-1")
    second = build_handoff(value, project_id="shared", run_id="run-2")
    assert first["revision"] == second["revision"] == source_revision(value)
    assert first["handoff_key"] == second["handoff_key"]
    assert first["status"] == "ready"


def test_source_change_creates_new_revision() -> None:
    value = record("https://example.org/post/1")
    changed = json.loads(json.dumps(value))
    changed["content"]["text"] = "updated source text"
    assert source_revision(value) != source_revision(changed)


def test_ai26_date_floor_and_missing_source_time_are_excluded() -> None:
    old = build_handoff(
        record("https://example.org/old", collection_id="ai26", published="2026-08-31T23:59:59Z"),
        project_id="ai26",
    )
    missing = record("https://example.org/missing", collection_id="ai26")
    missing["source"]["created_at"] = None
    missing_handoff = build_handoff(missing, project_id="ai26")
    assert (old["status"], old["reason"]) == ("excluded", "before_publication_date_floor")
    assert (missing_handoff["status"], missing_handoff["reason"]) == (
        "excluded",
        "missing_source_publication_time",
    )


def test_media_moves_from_waiting_to_ready_after_downloader_state(tmp_path: Path) -> None:
    value = record("https://example.org/media/1", media=True)
    write_record(tmp_path, value)

    waiting = export_handoffs(tmp_path, project_id="shared", ready_only=False)
    assert waiting[0]["status"] == "waiting_media"

    store = CollectionStore(tmp_path)
    try:
        store.record_media(
            "brazil26:x:synthetic:0",
            "x",
            value["source_url"],
            0,
            "https://media.example/image.jpg",
            "media/brazil26/image.jpg",
            "abc123",
            123,
            "image/jpeg",
            "completed",
        )
    finally:
        store.close()

    ready = export_handoffs(tmp_path, project_id="shared")
    assert len(ready) == 1
    assert ready[0]["status"] == "ready"
    assert ready[0]["reason"] == "media_ready"


def test_collection_filter_and_keys_keep_campaigns_separate(tmp_path: Path) -> None:
    url = "https://example.org/shared"
    write_record(tmp_path, record(url, collection_id="ai26"))
    write_record(tmp_path, record(url, collection_id="brazil26"))
    ai = export_handoffs(tmp_path, project_id="shared", collection_id="ai26")
    brazil = export_handoffs(tmp_path, project_id="shared", collection_id="brazil26")
    assert len(ai) == len(brazil) == 1
    assert ai[0]["handoff_key"] != brazil[0]["handoff_key"]
