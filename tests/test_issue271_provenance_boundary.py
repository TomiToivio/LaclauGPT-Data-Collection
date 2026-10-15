"""#271: realistic producer source extensions remain intact at the 1.1 → 1.2 boundary.

This is a Collection contract test. Actual Analysis worker ingestion and Laskin
deployment remain separate release gates; neither is simulated here.
"""
import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from laclaugpt_data_collection.analysis_schema_compat import analysis_1_2_view

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "tests/fixtures/ai26_record_v1.json"
SCHEMA = ROOT / "schemas/analysis-research-record-1.2.0.schema.json"


def test_source_extensions_and_routing_metadata_survive_1_2_view():
    original = json.loads(RECORD.read_text(encoding="utf-8"))
    original["source"].update({
        "backfill": "#250",
        "backfilled_at": "20261012T071912Z",
        "future_provenance_key": {"batch": 2},
    })
    original.update({
        "project_id": "ai26",
        "collection_id": "ai26",
        "arena": "elites",
        "handoff": {"revision": "stable"},
    })
    unchanged = deepcopy(original)
    output = analysis_1_2_view(original)

    assert original == unchanged
    assert output["schema_version"] == "1.2.0"
    assert output["source_url"] == original["source_url"]
    assert output["source"] == original["source"]
    assert output["legacy"]["_collection_compat_extensions"] == {
        "project_id": "ai26",
        "collection_id": "ai26",
        "arena": "elites",
        "handoff": {"revision": "stable"},
    }
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(output)) == []
    assert analysis_1_2_view(output) == output
