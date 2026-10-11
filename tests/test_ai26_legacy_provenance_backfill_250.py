"""Issue #250: backfill must fail closed and must not target deferred X."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "backfill", ROOT / "scripts/backfill_ai26_legacy_provenance.py"
)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

GOOD = {
    "id": "507f1f77bcf86cd799439011",
    "source_url": "https://example.org/article",
    "platform": "rss",
    "arena": "elites",
    "source_name": "manually-reviewed-source",
    "evidence": "Exact canonical URL verified against source publication.",
}


def test_mapping_validates_evidence_and_allowed_platforms():
    assert tool.validate_mapping(GOOD) == GOOD
    with pytest.raises(ValueError):
        tool.validate_mapping({**GOOD, "platform": "x"})
    with pytest.raises(ValueError):
        tool.validate_mapping({**GOOD, "arena": "unknown"})
    with pytest.raises(ValueError):
        tool.validate_mapping({**GOOD, "evidence": "guess"})


def test_guard_restricts_to_existing_unattributed_ai26_record():
    pytest.importorskip("bson")
    q = tool.query_for(GOOD)
    assert q["project_id"] == "ai26"
    assert q["arena"] == ""
    assert q["source.platform"] == "rss"
    assert q["source_url"] == GOOD["source_url"]
    assert q["$or"] == [{"source.raw_ref": None}, {"source.raw_ref": ""}]


def test_mapping_rejects_duplicates(tmp_path):
    import json
    path = tmp_path / "mapping.jsonl"
    path.write_text(json.dumps(GOOD) + "\n" + json.dumps(GOOD) + "\n")
    with pytest.raises(ValueError, match="duplicate id"):
        tool.load_mappings(path)
