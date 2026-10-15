"""Schema-version compatibility between Collection and Analysis (issue #271).

Acceptance items 2 and 4: a fixture-based Collection to Analysis handoff acceptance that covers a
legacy 1.1.0 record *and* a 1.2.0 record, without destructive rewrites - and that pins the claim the
compatibility document makes, namely that the two versions differ in the version string alone.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.models import SCHEMA_VERSION

FIXTURE = Path(__file__).parent / "fixtures" / "ai26_phase1_handoff_v1.json"


def _record(version: str) -> dict:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["schema_version"] = version
    return payload


def test_the_two_versions_differ_in_the_version_string_alone() -> None:
    """The document claims no field semantics differ. Assert it, so a real change cannot slip past."""
    legacy, current = _record("1.1.0"), _record("1.2.0")
    legacy.pop("schema_version"), current.pop("schema_version")
    assert legacy == current


def test_the_producer_still_declares_1_1_0_and_the_fixture_agrees() -> None:
    assert SCHEMA_VERSION == "1.1.0"
    assert json.loads(FIXTURE.read_text(encoding="utf-8"))["schema_version"] == "1.1.0"


def test_a_legacy_record_produces_a_ready_handoff_envelope() -> None:
    record = _record("1.1.0")
    envelope = build_handoff(record, project_id="ai26", run_id="ai26-distributed-001")
    assert envelope["contract_version"] == "1.0"
    assert envelope["status"] == "ready"
    assert envelope["source_url"] == record["source_url"]


def test_a_current_record_produces_the_same_envelope_apart_from_nothing() -> None:
    """1.2.0 must not change the envelope: the envelope versions the transfer, not the record."""
    legacy = build_handoff(_record("1.1.0"), project_id="ai26", run_id="r")
    current = build_handoff(_record("1.2.0"), project_id="ai26", run_id="r")
    assert legacy == current


def test_handoff_identity_is_stable_across_repeats_and_follows_the_source() -> None:
    record = _record("1.1.0")
    first = build_handoff(record, project_id="ai26", run_id="r")
    again = build_handoff(copy.deepcopy(record), project_id="ai26", run_id="r")
    assert first["handoff_key"] == again["handoff_key"]
    assert first["revision"] == again["revision"]

    changed = copy.deepcopy(record)
    changed["source"]["created_at"] = "2026-09-18T09:30:00Z"
    assert build_handoff(changed, project_id="ai26", run_id="r")["handoff_key"] != first["handoff_key"]


def test_the_handoff_does_not_rewrite_the_records_schema_version() -> None:
    """Acceptance item 4: old and new records verified without destructive rewrites."""
    for version in ("1.1.0", "1.2.0"):
        record = _record(version)
        build_handoff(record, project_id="ai26", run_id="r")
        assert record["schema_version"] == version


def test_the_source_provenance_survives_into_the_record_the_envelope_points_at() -> None:
    """The envelope identifies the record; provenance lives in the record and must be intact."""
    record = _record("1.1.0")
    envelope = build_handoff(record, project_id="ai26", run_id="r")
    assert envelope["source_url"] == record["source_url"]
    assert record["provenance"], "the record carries provenance for the Analysis side to read"
    assert record["provenance"][0]["provenance_id"] == "prov-ai26-collection-001"
