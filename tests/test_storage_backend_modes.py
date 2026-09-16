from __future__ import annotations

from pathlib import Path

import pytest

from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.factory import build_record_store
from laclaugpt_data_collection.models import CanonicalRecord
from laclaugpt_data_collection.storage.csv import CSVRecordStore


def _record() -> CanonicalRecord:
    return CanonicalRecord(
        source_url="https://example.org/post/1?utm_source=test",
        analysis={
            "relationships": {
                "targets": ["https://example.org/post/2"],
                "reply_to": ["https://example.org/post/0"],
            },
            "embeddings": [
                {
                    "vector": [0.1, 0.2, 0.3],
                    "model": "synthetic-test-embedding",
                    "version": "1",
                }
            ],
        },
    )


def test_csv_mode_requires_no_external_service(tmp_path: Path) -> None:
    settings = Settings(record_backend="csv", csv_path=tmp_path / "records.csv")
    store = build_record_store(settings)
    assert isinstance(store, CSVRecordStore)
    store.upsert(_record())
    loaded = store.get("https://example.org/post/1")
    assert loaded is not None
    assert loaded.analysis["relationships"]["targets"] == ["https://example.org/post/2"]
    assert loaded.analysis["embeddings"][0]["vector"] == [0.1, 0.2, 0.3]


def test_auto_without_uri_stays_local(tmp_path: Path) -> None:
    settings = Settings(record_backend="auto", mongodb_uri="", csv_path=tmp_path / "records.csv")
    assert isinstance(build_record_store(settings), CSVRecordStore)


def test_auto_falls_back_when_mongodb_unreachable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fail(_: Settings):
        raise RuntimeError("synthetic connection failure")

    monkeypatch.setattr("laclaugpt_data_collection.factory._build_mongodb_store", fail)
    settings = Settings(
        record_backend="auto",
        mongodb_uri="mongodb://example.invalid:27017",
        csv_path=tmp_path / "records.csv",
    )
    assert isinstance(build_record_store(settings), CSVRecordStore)


def test_explicit_mongodb_is_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_: Settings):
        raise RuntimeError("synthetic connection failure")

    monkeypatch.setattr("laclaugpt_data_collection.factory._build_mongodb_store", fail)
    settings = Settings(record_backend="mongodb", mongodb_uri="mongodb://example.invalid:27017")
    with pytest.raises(RuntimeError, match="synthetic connection failure"):
        build_record_store(settings)


def test_csv_roundtrip_preserves_nested_enrichment(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    store = CSVRecordStore(path)
    record = _record()
    store.upsert(record)
    reloaded = CSVRecordStore(path).get(record.source_url)
    assert reloaded is not None
    assert reloaded.model_dump(mode="json") == record.model_dump(mode="json")
