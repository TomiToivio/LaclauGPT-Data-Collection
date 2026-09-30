from __future__ import annotations

from laclaugpt_data_collection import server_runner
from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.models import CanonicalRecord, ContentSection, SourceSection


class _MemoryStore:
    def __init__(self) -> None:
        self.records: list[CanonicalRecord] = []

    def upsert(self, record: CanonicalRecord) -> None:
        self.records.append(record)


def _record(*, created_at: str = "2026-01-15T00:00:00+00:00") -> CanonicalRecord:
    return CanonicalRecord(
        source_url="https://example.invalid/brazil26/rss-item",
        source=SourceSection(
            platform="rss",
            source_type="article",
            created_at=created_at,
            raw_metadata={"arena": "parliamentary"},
        ),
        content=ContentSection(text="Brazil26 source text"),
    )


def test_brazil26_phase1_rss_uses_local_record_store_without_distributed_backends(
    monkeypatch,
) -> None:
    store = _MemoryStore()
    monkeypatch.setattr(server_runner, "load_feed_manifest", lambda _path: [{"name": "feed", "feed_url": "https://example.invalid/feed"}])
    monkeypatch.setattr(server_runner, "collect_rss_records", lambda *args, **kwargs: ([_record()], []))

    from laclaugpt_data_collection import factory
    monkeypatch.setattr(factory, "build_record_store", lambda settings: store)

    settings = Settings(
        _env_file=None,
        project_id="brazil26",
        record_backend="csv",
        mongodb_uri="",
        redis_url="",
        object_backend="filesystem",
        cache_backend="memory",
        distributed_config_backend="local",
        messaging_backend="none",
        task_queue_backend="direct",
    )

    summary = server_runner.run_phase1_rss(
        settings,
        study_config="unused-in-local-mode.yaml",
        source_manifest="synthetic.toml",
        collection_id="brazil26",
        rotation=0,
    )

    assert summary["status"] == "ok"
    assert summary["storage_mode"] == "local"
    assert summary["records_synced"] == 1
    assert summary["mongodb_collection"] == ""
    assert len(store.records) == 1


def test_brazil26_does_not_inherit_ai26_publication_floor(monkeypatch) -> None:
    store = _MemoryStore()
    monkeypatch.setattr(server_runner, "load_feed_manifest", lambda _path: [{"name": "feed", "feed_url": "https://example.invalid/feed"}])
    # This predates the AI26 2026-09-01 floor and must still be retained for Brazil26.
    monkeypatch.setattr(
        server_runner,
        "collect_rss_records",
        lambda *args, **kwargs: ([_record(created_at="2026-01-15T00:00:00+00:00")], []),
    )

    from laclaugpt_data_collection import factory
    monkeypatch.setattr(factory, "build_record_store", lambda settings: store)

    settings = Settings(_env_file=None, project_id="brazil26", record_backend="csv")

    summary = server_runner.run_phase1_rss(
        settings,
        study_config="unused-in-local-mode.yaml",
        source_manifest="synthetic.toml",
        collection_id="brazil26",
        rotation=0,
    )

    assert summary["records_synced"] == 1
    assert summary["skipped_before_publication_floor"] == 0


def test_ai26_keeps_its_publication_floor_in_local_mode(monkeypatch) -> None:
    store = _MemoryStore()
    monkeypatch.setattr(server_runner, "load_feed_manifest", lambda _path: [{"name": "feed", "feed_url": "https://example.invalid/feed"}])
    monkeypatch.setattr(
        server_runner,
        "collect_rss_records",
        lambda *args, **kwargs: ([_record(created_at="2026-01-15T00:00:00+00:00")], []),
    )

    from laclaugpt_data_collection import factory
    monkeypatch.setattr(factory, "build_record_store", lambda settings: store)

    settings = Settings(_env_file=None, project_id="ai26", record_backend="csv")

    summary = server_runner.run_phase1_rss(
        settings,
        study_config="unused-in-local-mode.yaml",
        source_manifest="synthetic.toml",
        collection_id="ai26",
        rotation=0,
    )

    assert summary["records_synced"] == 0
    assert summary["skipped_before_publication_floor"] == 1
    assert store.records == []
