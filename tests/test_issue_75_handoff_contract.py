"""Issue #75: pin the Collection -> Analysis Phase 1 AI26 handoff contract.

Collection and Analysis define **separate** canonical models with the same name and
different shapes:

* Collection `models.CanonicalRecord` — nested sections, `source_native_ids`,
  media references carrying `kind`/`media_type`/`ref`/`media_index`.
* Analysis `canonical.CanonicalRecord` — nested sections plus research layers
  (`intermediate`/`evidence`/`review`/`legacy`), bridged by
  `laclaugpt_data_analysis.interchange.from_collection_record`.

Nothing exercised that boundary, so the two schemas could drift while both
repositories' local suites stayed green. This module validates the *Collection*
half of the versioned contract: the record Collection emits, plus the delivery
envelope produced by `build_handoff`.

The fixture is shared with the Analysis repository, which converts the same bytes
via its adapter. Both repositories therefore assert the same contract.
"""
from __future__ import annotations

import json
from pathlib import Path

from laclaugpt_data_collection.models import CanonicalRecord

FIXTURE = Path(__file__).parent / "fixtures" / "ai26_collection_handoff_v1.json"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _record_payload() -> dict:
    """The record itself, without the delivery envelope."""
    return {key: value for key, value in _payload().items() if key != "handoff"}


# --------------------------------------------------------------------------
# The handoff schema is versioned and explicit
# --------------------------------------------------------------------------

def test_fixture_declares_the_handoff_contract_version() -> None:
    payload = _payload()
    assert payload["handoff"]["contract_version"] == "1.0"
    assert payload["schema_version"] == "1.1.0-draft"


def test_handoff_envelope_carries_routing_metadata() -> None:
    envelope = _payload()["handoff"]
    for key in ("handoff_key", "revision", "status", "project_id", "arena", "run_id"):
        assert envelope.get(key), f"handoff envelope must declare {key}"
    assert envelope["status"] == "ready"


def test_fixture_is_analysis_neutral() -> None:
    """Collection owns source provenance; Laclaudian codes belong downstream."""
    blob = json.dumps(_payload()).casefold()
    for field in (
        "formations", "signifiers", "nodal_points", "empty_signifier",
        "floating_signifier", "equivalence", "antagonism", "formula_of_populism",
        "chains_of_equivalence", "demands",
    ):
        assert field not in blob, f"collection record must not carry {field!r}"


# --------------------------------------------------------------------------
# Collection validates the record it hands over
# --------------------------------------------------------------------------

def test_collection_model_accepts_the_handoff_fixture() -> None:
    record = CanonicalRecord.model_validate(_record_payload())
    assert record.source_url == "https://example.invalid/ai26/synthetic/post-001"


def test_fixture_preserves_native_ids() -> None:
    record = CanonicalRecord.model_validate(_record_payload())
    assert record.source_native_ids["document_id"] == "ai26-synthetic-001"
    assert record.source_native_ids["x_post_id"] == "1234567890"


def test_fixture_preserves_timestamps() -> None:
    """Collection timestamps are preserved verbatim (ISO-8601 strings on this section)."""
    record = CanonicalRecord.model_validate(_record_payload())
    assert record.source.created_at
    assert str(record.source.created_at).startswith("2026-09-18T09:30:00")
    assert str(record.source.collected_at).startswith("2026-09-18T10:00:00")


def test_fixture_preserves_language_and_source_metadata() -> None:
    record = CanonicalRecord.model_validate(_record_payload())
    assert record.content.language == "en"
    assert record.source.platform == "x"
    assert record.source.author == "synthetic-author"


def test_fixture_preserves_media_reference_fields() -> None:
    record = CanonicalRecord.model_validate(_record_payload())
    media = record.content.media_references[0]
    assert media.media_type == "image"
    assert media.ref == "fixture://ai26-handoff-v1/media/001"
    assert media.media_index == 0
    assert media.kind == "image"


def test_fixture_preserves_frame_references() -> None:
    record = CanonicalRecord.model_validate(_record_payload())
    assert record.content.frames
    assert record.content.frames[0]["media_ref"].startswith("fixture://")


def test_fixture_preserves_provenance() -> None:
    record = CanonicalRecord.model_validate(_record_payload())
    assert record.provenance
    assert record.provenance[0].method == "browser-capture"


def test_fixture_preserves_raw_reference() -> None:
    record = CanonicalRecord.model_validate(_record_payload())
    assert record.raw_capture.ref.endswith("raw/001.json")
