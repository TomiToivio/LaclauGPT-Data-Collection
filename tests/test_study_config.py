"""Study-config and normalization tests (synthetic configs only)."""
from __future__ import annotations

import pytest
import yaml

from laclaugpt_data_collection.collectors.platforms import tiktok_extras
from laclaugpt_data_collection.normalize import dedup_key, is_aux_platform, normalise, normalise_aux
from laclaugpt_data_collection.study import load_config
from tests.fixtures import tiktok_synthetic as tfx

SYNTHETIC_STUDY = {
    "study": "synthetic",
    "window": {"start": "2020-01-01", "end": "2030-01-01"},
    "timezone": "UTC",
    "platforms": {"tiktok": {"enabled": True, "base_urls": ["https://www.tiktok.com/@{handle}"]}},
    "groups": [{"id": "g", "name": "G", "accounts": {"tiktok": ["ok_handle"]}}],
}


def test_study_config_accounts(tmp_path) -> None:
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(SYNTHETIC_STUDY), encoding="utf-8")
    cfg = load_config(path)
    rows = cfg.accounts()
    assert rows == [{"name": "G", "kind": "group", "platform": "tiktok",
                     "handle": "ok_handle", "group_id": "g",
                     "formation_seed": "", "arena": "", "notes": ""}]
    assert cfg.in_window()
    assert cfg.missing_candidates() == []


def test_study_config_rejects_empty_handles(tmp_path) -> None:
    bad = {**SYNTHETIC_STUDY, "groups": [{"id": "g", "accounts": {"tiktok": ["   "]}}]}
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="handles"):
        load_config(path)


def test_normalise_raises_without_id() -> None:
    with pytest.raises(ValueError):
        normalise("tiktok", {"author": "x"})


def test_aux_normalisation_roundtrip() -> None:
    mapped = tiktok_extras.map_item(tfx.COMMENT)
    record = normalise_aux("tiktok_comment", mapped, raw_ref="raw/x.ndjson")
    assert record.raw_ref == "raw/x.ndjson"
    assert dedup_key(record) == ("tiktok_comment", "c-0001")
    assert is_aux_platform("tiktok_comment")
    assert not is_aux_platform("tiktok")


def test_normalise_provenance_defaults() -> None:
    mapped = {"id": "x1", "author": "a", "body": "b", "link": "https://example.invalid/1"}
    record = normalise("tiktok", mapped)
    assert record.collection_provenance.module == "laclaugpt-native-tiktok-2026-09"
    assert record.collection_provenance.transformations == [
        "laclaugpt-network-capture", "map-item-normalise"]