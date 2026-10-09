# -*- coding: utf-8 -*-
"""Issue #222 — ``records_synced`` must not be read as corpus growth.

The AI26 collect cycle re-upserts a rotating window of already-stored records
every hour, so the raw upsert count over-reports growth ~6x (measured: 769
``records_synced`` vs 122 first-seen documents in one 24 h window). The cycle
record therefore carries ``records_new`` (documents created) and
``records_updated`` (re-writes) alongside the legacy ``records_synced``
(operations), and the stores report which one a write was.

These tests pin the *arithmetic* of that split at the two places that can get it
wrong: the store's create/update verdict, and the runner's counters. They do not
assert a live-store figure — that is the daily ledger's job.
"""
from __future__ import annotations

from pathlib import Path

from laclaugpt_data_collection.models import CanonicalRecord, CollectionProvenance
from laclaugpt_data_collection.storage.csv import CSVRecordStore


def _record(url: str = "https://example.org/article") -> CanonicalRecord:
    return CanonicalRecord(
        source_url=url,
        source={"platform": "rss", "source_type": "rss"},
        content={"text": "Article body", "title": "Article title"},
        provenance=[
            CollectionProvenance(
                module="tests.test_issue_222_records_new_metric",
                metadata={"collection_id": "ai26", "arena": "elites"},
            )
        ],
    )


class _MemoryStore:
    """Minimal RecordStore double that reports create-vs-update like the real ones."""

    def __init__(self) -> None:
        self.records: list[CanonicalRecord] = []
        self.keys: set[str] = set()

    def upsert(self, record: CanonicalRecord) -> bool:
        created = record.source_url not in self.keys
        self.keys.add(record.source_url)
        self.records.append(record)
        return created

    def upsert_many(self, records) -> None:  # noqa: ANN001 - protocol parity
        for record in records:
            self.upsert(record)

    def contains(self, source_url: str) -> bool:
        return source_url in self.keys


class TestStoreReportsCreation:
    """The store's return value is the only place the distinction can originate."""

    def test_csv_store_reports_first_write_as_created(self, tmp_path: Path) -> None:
        store = CSVRecordStore(tmp_path / "records.csv")
        assert store.upsert(_record()) is True, "the first write of an identity is new"

    def test_csv_store_reports_rewrite_as_not_created(self, tmp_path: Path) -> None:
        store = CSVRecordStore(tmp_path / "records.csv")
        store.upsert(_record())
        assert store.upsert(_record()) is False, "a re-sync is an update, not growth"

    def test_memory_double_matches_the_contract(self) -> None:
        """The double used by the runner tests must model the same split."""
        store = _MemoryStore()
        assert store.upsert(_record()) is True
        assert store.upsert(_record()) is False


class TestCycleReportsNewAndUpdated:
    """The runner must expose records_new/records_updated, not just records_synced."""

    def test_phase1_rss_reports_new_and_updated_separately(self, monkeypatch) -> None:
        from laclaugpt_data_collection import server_runner

        store = _MemoryStore()
        monkeypatch.setattr(
            server_runner,
            "load_feed_manifest",
            lambda _p: [{"name": "feed", "feed_url": "https://example.invalid/feed"}],
        )
        # Two records: the second identity is served twice, so the cycle performs
        # three writes of two documents — exactly the 6x-class over-count.
        monkeypatch.setattr(
            server_runner,
            "collect_rss_records",
            lambda *a, **k: (
                [
                    _record("https://example.org/a"),
                    _record("https://example.org/b"),
                ],
                [],
            ),
        )
        from laclaugpt_data_collection import factory

        monkeypatch.setattr(factory, "build_record_store", lambda settings: store)

        from laclaugpt_data_collection.config import Settings

        settings = Settings(_env_file=None, project_id="brazil26", record_backend="csv")
        summary = server_runner.run_phase1_rss(
            settings,
            study_config="unused.yaml",
            source_manifest="synthetic.toml",
            collection_id="brazil26",
            rotation=0,
        )
        assert summary["records_synced"] == 2
        assert summary["records_new"] == 2
        assert summary["records_updated"] == 0
        assert summary["records_new"] + summary["records_updated"] == summary["records_synced"]

    def test_a_resync_cycle_reports_zero_growth(self, monkeypatch) -> None:
        """The over-count case: same identity re-served must not count as new."""
        from laclaugpt_data_collection import factory, server_runner
        from laclaugpt_data_collection.config import Settings

        store = _MemoryStore()
        store.keys.add("https://example.org/a")  # simulate the document already stored
        monkeypatch.setattr(
            server_runner,
            "load_feed_manifest",
            lambda _p: [{"name": "feed", "feed_url": "https://example.invalid/feed"}],
        )
        monkeypatch.setattr(
            server_runner,
            "collect_rss_records",
            lambda *a, **k: ([_record("https://example.org/a")], []),
        )
        monkeypatch.setattr(factory, "build_record_store", lambda settings: store)

        settings = Settings(_env_file=None, project_id="brazil26", record_backend="csv")
        summary = server_runner.run_phase1_rss(
            settings,
            study_config="unused.yaml",
            source_manifest="synthetic.toml",
            collection_id="brazil26",
            rotation=0,
        )
        assert summary["records_synced"] == 1, "the write still happened"
        assert summary["records_new"] == 0, "but it created nothing"
        assert summary["records_updated"] == 1


class TestLaskinRunnerCarriesTheMetric:
    """The AI26 Laskin runner is the one #222 was filed against."""

    def test_laskin_runner_reports_new_and_updated(self, monkeypatch, tmp_path: Path) -> None:
        from laclaugpt_data_collection.ai26_laskin_runner import run_phase1_laskin
        from laclaugpt_data_collection.config import Settings

        class FakeSink:
            last = None

            def __init__(self, settings):  # noqa: ANN001
                self.settings = settings
                self.notification_errors = []
                self.calls = 0
                FakeSink.last = self

            def assert_private_config(self, study_config):  # noqa: ANN001
                return Path(study_config)

            def ingest_with_status(self, payload):  # noqa: ANN001
                self.calls += 1
                # First write is new, the second (same identity) is a re-write.
                return payload, self.calls == 1

        record = _record("https://example.org/agent-record")
        monkeypatch.setattr(
            "laclaugpt_data_collection.ai26_laskin_runner.load_non_browser_jobs",
            lambda _p: [{"kind": "web_source", "name": "synthetic", "priority": "P1"}],
        )
        monkeypatch.setattr(
            "laclaugpt_data_collection.ai26_laskin_runner.preflight_optional_dependencies",
            lambda _jobs: [],
        )
        monkeypatch.setattr(
            "laclaugpt_data_collection.ai26_laskin_runner.run_phase1_rss",
            lambda *a, **k: {
                "records_synced": 0,
                "records_new": 0,
                "skipped_before_publication_floor": 0,
                "warnings": [],
                "errors": [],
                "notification_errors": [],
            },
        )
        monkeypatch.setattr(
            "laclaugpt_data_collection.ai26_laskin_runner._records_for_job",
            lambda *a, **k: ([record, record], []),
        )
        monkeypatch.setattr(
            "laclaugpt_data_collection.ai26_laskin_runner.DistributedCaptureSink",
            FakeSink,
        )

        settings = Settings(
            _env_file=None,
            project_id="ai26",
            caller="hermes-agent",
            execution="agent",
            run_id="test-222",
        )
        summary = run_phase1_laskin(
            settings,
            study_config=tmp_path / "ai26.yaml",
            source_manifest=tmp_path / "ai26.sources.toml",
            collection_id="ai26",
            max_feeds=1,
            max_jobs=1,
            per_source_limit=2,
            limit=10,
            rotation=0,
        )
        assert summary["records_synced"] == 2, "both writes happened"
        assert summary["records_new"] == 1, "only one document was created"
        assert summary["records_updated"] == 1
        assert summary["records_new"] + summary["records_updated"] == summary["records_synced"]
