"""AI26 Phase 1 Collection -> Analysis handoff contract."""

from __future__ import annotations

import json
from pathlib import Path

from laclaugpt_data_collection.models import SCHEMA_VERSION, CanonicalRecord

FIXTURE = Path(__file__).parent / "fixtures" / "ai26_phase1_handoff_v1.json"


def test_ai26_phase1_handoff_fixture_is_canonical_and_analysis_neutral() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    record = CanonicalRecord.model_validate(
        {key: value for key, value in payload.items() if key != "contract_version"}
    )

    assert payload["contract_version"] == "ai26-phase1-handoff-v1"
    assert record.schema_version == SCHEMA_VERSION == "1.1.0"
    assert record.source_url == payload["source_url"]
    assert record.source_native_ids == payload["source_native_ids"]
    assert record.source.created_at == "2026-09-18T09:00:00Z"
    assert record.source.collected_at == "2026-09-18T09:00:05Z"
    assert record.source.language == "en"
    assert record.content.language == "en"
    assert record.content.text == payload["content"]["text"]

    assert record.content.media_references[0].ref == "fixture://ai26-phase1/media/video-001"
    assert record.content.frames[0]["media_ref"] == "fixture://ai26-phase1/frame/004"
    assert record.intermediate.frames[0]["media_ref"] == "fixture://ai26-phase1/frame/004"

    assert record.raw_capture.ref == "fixture://ai26-phase1/raw/001"
    assert record.provenance[0].provenance_id == "prov-ai26-collection-001"
    assert record.provenance[0].metadata["contract_version"] == payload["contract_version"]

    assert record.analysis == {}
    assert record.evidence == []
    assert record.review == {}
