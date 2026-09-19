from pathlib import Path

from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.models import CanonicalRecord, CollectionProvenance
from laclaugpt_data_collection.storage.local import SQLiteRecordStore


def _record(*, text: str = "stable source text", media: bool = False) -> CanonicalRecord:
    media_references = []
    if media:
        media_references = [{"kind": "video", "url": "https://media.example.invalid/video.mp4"}]
    return CanonicalRecord(
        source_url="https://example.invalid/source/phase1",
        source_native_ids={"platform_post_id": "native-1"},
        source={
            "platform": "synthetic",
            "source_type": "api",
            "created_at": "2026-09-18T12:00:00Z",
            "raw_metadata": {"collection_id": "SYNTH26"},
        },
        content={"text": text, "media_references": media_references},
        provenance=[
            CollectionProvenance(
                run_id="run-1",
                module="collection-plugin:synthetic",
                metadata={"collection_id": "SYNTH26"},
            )
        ],
    )


def test_stored_record_produces_deterministic_analysis_handoff(tmp_path: Path) -> None:
    store = SQLiteRecordStore(tmp_path / "phase1.sqlite3")
    record = _record()
    store.upsert(record)
    restored = store.get(record.source_url)
    assert restored is not None

    first = build_handoff(restored.model_dump(mode="json"), project_id="phase1")
    second = build_handoff(restored.model_dump(mode="json"), project_id="phase1")

    assert first == second
    assert first["status"] == "ready"
    assert first["reason"] == "source_ready"
    assert "analysis" not in first
    assert "evidence" not in first

    changed = _record(text="analysis-relevant source text changed")
    changed_handoff = build_handoff(changed.model_dump(mode="json"), project_id="phase1")
    assert changed_handoff["revision"] != first["revision"]
    assert changed_handoff["handoff_key"] != first["handoff_key"]


def test_unresolved_media_waits_without_fabricating_analysis_state() -> None:
    handoff = build_handoff(_record(media=True).model_dump(mode="json"), project_id="phase1")
    assert handoff["status"] == "waiting_media"
    assert handoff["reason"] == "waiting_media"
    assert "analysis" not in handoff
    assert "labels" not in handoff
