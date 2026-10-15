"""Offline compatibility acceptance for Collection issue #271 / Analysis #341."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from laclaugpt_data_collection.analysis_schema_compat import analysis_1_2_view
from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.models import CanonicalRecord


FIXTURE = Path(__file__).parent / "fixtures" / "ai26_phase1_handoff_v1.json"


def legacy_record():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload.pop("contract_version")
    return CanonicalRecord.model_validate(payload).model_dump(mode="json")


def test_vendored_analysis_schema_accepts_both_versions_via_adapter():
    schema_path = Path(__file__).parents[1] / 'schemas' / 'analysis-research-record-1.2.0.schema.json'
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    validator = Draft202012Validator(schema)
    for version in ('1.1.0', '1.2.0'):
        value = legacy_record()
        value['schema_version'] = version
        errors = list(validator.iter_errors(analysis_1_2_view(value)))
        assert not errors, [str(err) for err in errors]


def test_legacy_1_1_projects_to_1_2_without_mutating_source():
    original = legacy_record()
    snapshot = deepcopy(original)
    projected = analysis_1_2_view(original)
    assert original == snapshot
    assert original["schema_version"] == "1.1.0"
    assert projected["schema_version"] == "1.2.0"
    for field in ("source_url", "source_native_ids", "raw_capture", "source",
                  "content", "intermediate", "provenance", "review", "analysis"):
        assert projected[field] == original[field]
    assert projected["legacy"]["_collection_compat_extensions"]["source_units"] == []
    assert projected["legacy"]["_collection_compat_extensions"]["alignments"] == []


def test_existing_1_2_is_idempotent_and_not_rewritten():
    original = analysis_1_2_view(legacy_record())
    assert analysis_1_2_view(original) == original


def test_text_only_ready_and_stable_handoff_identity():
    record = legacy_record()
    record["content"]["media_references"] = []
    record["content"]["frames"] = []
    record["intermediate"]["frames"] = []
    record["collection_id"] = "ai26"
    record["arena"] = "elites"
    handoff_a = build_handoff(record, project_id="ai26", run_id="one")
    handoff_b = build_handoff(record, project_id="ai26", run_id="two")
    assert handoff_a["status"] == "ready"
    assert handoff_a["source_url"] == record["source_url"]
    assert handoff_a["handoff_key"] == handoff_b["handoff_key"]
    assert handoff_a["revision"] == handoff_b["revision"]
    assert handoff_a["arena"] == "elites"
    assert analysis_1_2_view(record)["provenance"] == record["provenance"]


def test_changed_content_changes_revision():
    value = legacy_record()
    value["collection_id"] = "ai26"
    changed = deepcopy(value)
    changed["content"]["text"] += " updated"
    assert build_handoff(value)["revision"] != build_handoff(changed)["revision"]


@pytest.mark.parametrize("version", ["1.0.0", "1.3.0", None])
def test_unknown_versions_fail_closed(version):
    value = legacy_record()
    value["schema_version"] = version
    with pytest.raises(ValueError, match="unsupported"):
        analysis_1_2_view(value)


def test_invalid_or_conflicting_extra_state_refused():
    value = legacy_record()
    value["legacy"]["_collection_compat_extensions"] = {"existing": True}
    with pytest.raises(ValueError, match="reserved"):
        analysis_1_2_view(value)
