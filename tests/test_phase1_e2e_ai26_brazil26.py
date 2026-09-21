from __future__ import annotations

import hashlib
import json
from pathlib import Path

from laclaugpt_data_collection.models import SCHEMA_VERSION, CanonicalRecord

FIXTURE = Path(__file__).parent / "fixtures" / "phase1_e2e_ai26_brazil26_v1.json"


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _identity(row: dict) -> tuple[str, str, str]:
    return (
        row["project_id"],
        row["collection_id"],
        CanonicalRecord.model_validate(row["record"]).source_url,
    )


def _analysis_identity(row: dict) -> str:
    project_id, collection_id, source_url = _identity(row)
    payload = f"{project_id}\0{collection_id}\0{source_url}\0phase1-analysis-v1"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _visualization_select(rows: list[dict], collection_id: str | None) -> list[dict]:
    if collection_id is None:
        return rows
    return [row for row in rows if row["collection_id"] == collection_id]


def test_fixture_exercises_required_two_study_two_machine_topology() -> None:
    payload = _load()
    topology = payload["topology"]
    assert topology["localhost"]["browser"] == ["ai26", "brazil26"]
    assert topology["localhost"]["non_browser"] == ["ai26", "brazil26"]
    assert topology["laskin"]["browser"] == []
    assert topology["laskin"]["non_browser"] == ["ai26", "brazil26"]
    assert topology["laskin"]["shared_media_worker"] is True

    rows = payload["records"]
    observed = {
        (row["collection_id"], row["machine"], row["execution"])
        for row in rows
    }
    assert observed == {
        ("ai26", "localhost", "browser"),
        ("ai26", "laskin", "non-browser"),
        ("brazil26", "localhost", "browser"),
        ("brazil26", "laskin", "non-browser"),
    }


def test_all_records_are_one_canonical_schema_and_preserve_routing() -> None:
    payload = _load()
    assert payload["contract"]["canonical_schema_version"] == SCHEMA_VERSION == "1.1.0"
    assert payload["contract"]["ai26_handoff_contract"] == "ai26-phase1-handoff-v1"

    for row in payload["records"]:
        record = CanonicalRecord.model_validate(row["record"])
        assert record.schema_version == SCHEMA_VERSION
        assert row["collection_id"] in {"ai26", "brazil26"}
        assert row["project_id"] == row["collection_id"]
        assert record.source.raw_metadata["collection_id"] == row["collection_id"]
        metadata = record.provenance[0].metadata
        assert metadata["project_id"] == row["project_id"]
        assert metadata["collection_id"] == row["collection_id"]
        assert metadata["machine"] == row["machine"]
        assert metadata["execution"] == row["execution"]


def test_same_public_url_can_exist_in_both_studies_without_erasure() -> None:
    rows = _load()["records"]
    shared = [row for row in rows if row["record"]["source_url"].endswith("/shared/phase1")]
    assert len(shared) == 2
    assert {row["collection_id"] for row in shared} == {"ai26", "brazil26"}
    assert len({_identity(row) for row in shared}) == 2


def test_rerun_is_idempotent_for_canonical_and_analysis_identity() -> None:
    rows = _load()["records"]
    first_canonical = {_identity(row) for row in rows}
    second_canonical = {_identity(row) for row in rows + rows}
    assert first_canonical == second_canonical
    assert len(first_canonical) == 4

    first_analysis = {_analysis_identity(row) for row in rows}
    second_analysis = {_analysis_identity(row) for row in rows + rows}
    assert first_analysis == second_analysis
    assert len(first_analysis) == 4


def test_analysis_can_consume_both_studies_without_schema_translation() -> None:
    rows = _load()["records"]
    outputs = []
    for row in rows:
        record = CanonicalRecord.model_validate(row["record"])
        enriched = record.model_copy(deep=True)
        enriched.analysis["phase1_fixture"] = {
            "analysis_id": _analysis_identity(row),
            "project_id": row["project_id"],
            "collection_id": row["collection_id"],
            "summary": f"synthetic analysis for {row['collection_id']}",
        }
        outputs.append(
            {
                "project_id": row["project_id"],
                "collection_id": row["collection_id"],
                "record": enriched.model_dump(mode="json"),
            }
        )

    assert len(outputs) == 4
    assert {row["collection_id"] for row in outputs} == {"ai26", "brazil26"}
    for output in outputs:
        validated = CanonicalRecord.model_validate(output["record"])
        analysis = validated.analysis["phase1_fixture"]
        assert analysis["collection_id"] == output["collection_id"]
        assert analysis["project_id"] == output["project_id"]


def test_visualization_selection_is_explicit_and_never_silently_merges_identity() -> None:
    rows = _load()["records"]
    ai26 = _visualization_select(rows, "ai26")
    brazil26 = _visualization_select(rows, "brazil26")
    combined = _visualization_select(rows, None)

    assert len(ai26) == 2
    assert len(brazil26) == 2
    assert len(combined) == 4
    assert {row["collection_id"] for row in ai26} == {"ai26"}
    assert {row["collection_id"] for row in brazil26} == {"brazil26"}
    assert len({_identity(row) for row in combined}) == 4


def test_object_refs_and_configuration_revisions_remain_project_scoped() -> None:
    rows = _load()["records"]
    media = [
        media
        for row in rows
        for media in row["record"].get("content", {}).get("media_references", [])
    ]
    assert media
    assert all("/projects/ai26/" in item["object_ref"] for item in media)

    for row in rows:
        metadata = row["record"]["provenance"][0]["metadata"]
        for key in (
            "study_config_revision",
            "collection_codebook_revision",
            "source_manifest_revision",
        ):
            assert metadata[key].startswith("sha256:")
            assert len(metadata[key]) > len("sha256:")


def test_laskin_fixture_never_uses_browser_only_platforms() -> None:
    browser_only = {"x", "instagram", "tiktok", "firefox"}
    laskin = [row for row in _load()["records"] if row["machine"] == "laskin"]
    assert laskin
    for row in laskin:
        assert row["execution"] == "non-browser"
        assert row["record"]["source"]["platform"].lower() not in browser_only
