from pathlib import Path

from laclaugpt_data_collection.collectors.base import CollectionResult
from laclaugpt_data_collection.models import NormalizedRecord
from laclaugpt_data_collection.plugins import (
    CollectionContext,
    CollectionRunner,
    PluginRegistry,
    PluginSpec,
    adapt_collector,
)
from laclaugpt_data_collection.storage.local import SQLiteRecordStore


class SyntheticPhase1Collector:
    def collect(self) -> CollectionResult:
        return CollectionResult(
            records=[
                NormalizedRecord(
                    document_id="native-42",
                    platform="synthetic",
                    source_url="https://EXAMPLE.invalid/items/42/?utm_source=phase1",
                    text="Phase 1 synthetic canonical payload",
                    raw_payload={
                        "id": "native-42",
                        "body": "Phase 1 synthetic canonical payload",
                        "fixture": True,
                    },
                    raw_content_type="application/json",
                )
            ],
            raw_items_seen=1,
        )


def test_phase1_plugin_to_sqlite_is_idempotent_and_lossless(tmp_path: Path) -> None:
    registry = PluginRegistry()
    registry.register(
        adapt_collector(
            PluginSpec(
                plugin_id="phase1-synthetic",
                version="1.0.0",
                source_type="synthetic",
                modes=("batch",),
            ),
            lambda _context: SyntheticPhase1Collector(),
        )
    )
    store = SQLiteRecordStore(tmp_path / "phase1.sqlite3")
    runner = CollectionRunner(registry, store)
    context = CollectionContext(
        project_id="phase1-test",
        collection_id="AI26",
        arena="fixture",
        run_id="phase1-run",
        privacy={"access": "fixture-only", "publish_raw": False},
    )

    first = runner.run("phase1-synthetic", context)
    second = runner.run("phase1-synthetic", context)

    assert first.records_written == 1
    assert first.duplicates_skipped == 0
    assert second.records_written == 0
    assert second.duplicates_skipped == 1

    records = store.all()
    assert len(records) == 1
    restored = records[0]
    assert restored.source_url == "https://example.invalid/items/42"
    assert restored.source_native_ids == {"document_id": "native-42"}
    assert restored.content.text == "Phase 1 synthetic canonical payload"
    assert restored.raw_capture.preserved
    assert restored.raw_capture.payload == {
        "id": "native-42",
        "body": "Phase 1 synthetic canonical payload",
        "fixture": True,
    }
    assert restored.raw_capture.content_type == "application/json"
    assert restored.provenance[-1].module == "collection-plugin:phase1-synthetic"
    assert restored.provenance[-1].metadata["collection_id"] == "AI26"
    assert restored.provenance[-1].metadata["privacy"]["access"] == "fixture-only"

    round_trip = store.get(restored.source_url)
    assert round_trip is not None
    assert round_trip.model_dump(mode="json") == restored.model_dump(mode="json")
