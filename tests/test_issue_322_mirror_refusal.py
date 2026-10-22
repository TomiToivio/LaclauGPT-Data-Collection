"""Regression coverage for issue #322: the writer must refuse and report a hollow row.

PR #323 already made `DistributedCaptureSink` refuse a record with no text, no raw
payload/ref and no media. These tests cover the part that shipped without it, which is
where the 1,703 rows actually came from on 2026-10-22 10:53-10:54 UTC:

* `JsonlDistributedMirror.scan_once` (the AI26 Firefox mirror, started by the operator
  command from #320) replays whatever canonical JSONL is on disk and called
  `sink.ingest` unguarded, so a backlog of bare X post URLs became 1,703 documents with
  empty `content.text`, null `raw_capture.payload`/`checksum`, blank
  `source.platform`/`author` and no native id -- with no `source_outcomes` of their own
  and no cycle claiming them.
* With only the sink guard in place, the first such row raised out of the pre-bind
  replay, so capture could not start at all and the thread retried the same offset
  forever: fail-closed but silent and wedging, with no way to see which source or URL.

The refusal is now reported per source file and URL, and the offset advances past it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from laclaugpt_data_collection import ai26_browser, distributed_sync
from laclaugpt_data_collection import ai26_laskin_runner as runner
from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.deployment import DeploymentProfile, apply_profile
from laclaugpt_data_collection.distributed_capture import (
    HOLLOW_RECORD_REASON,
    DistributedCaptureSink,
    HollowRecordError,
)
from laclaugpt_data_collection.models import (
    CanonicalRecord,
    CollectionProvenance,
    NormalizedRecord,
)

HOLLOW_URL = "https://x.com/PauseAI/status/2085033275710415126"


class FakeMongo:
    def __init__(self, uri, database, collection, project_id):
        self.uri = uri
        self.database = database
        self.collection = collection
        self.project_id = project_id
        self.records = []

    def upsert(self, record):
        self.records.append(record)


class FakeS3:
    def __init__(self, *, bucket, prefix, **kwargs):
        self.bucket = bucket
        self.prefix = prefix
        self.objects = {}

    def put_bytes(self, key, payload, *, content_type="application/octet-stream"):
        self.objects[key] = (payload, content_type)
        return f"s3://{self.bucket}/{self.prefix}/{key}"


class FakeRedis:
    def __init__(self, url, namespace):
        self.url = url
        self.namespace = namespace
        self.events = []

    def ping(self):
        return True

    def publish_stream(self, name, fields, *, maxlen=100000):
        self.events.append((name, fields))
        return "1-0"

    def acquire_once(self, key, *, ttl_seconds):
        del key, ttl_seconds
        return True


def distributed_settings(tmp_path: Path) -> Settings:
    private = tmp_path / "private"
    private.mkdir()
    return apply_profile(
        Settings(
            _env_file=None,
            project_id="ai26",
            run_id="ai26-smoke-001",
            mongodb_uri="mongodb://example.invalid:27017",
            redis_url="redis://example.invalid:6379/0",
            messaging_backend="redis",
            s3_bucket="laclaugpt-test",
            private_config_dir=private,
            data_root=tmp_path / "data",
        ),
        DeploymentProfile.laptop_firefox_distributed(),
    )


def _sink(tmp_path: Path, monkeypatch) -> DistributedCaptureSink:
    settings = distributed_settings(tmp_path)
    monkeypatch.setattr(
        "laclaugpt_data_collection.distributed_capture.MongoRecordStore", FakeMongo
    )
    monkeypatch.setattr(
        "laclaugpt_data_collection.distributed_capture.S3ObjectStore", FakeS3
    )
    monkeypatch.setattr(
        "laclaugpt_data_collection.distributed_capture.RedisCoordinator", FakeRedis
    )
    return DistributedCaptureSink(settings)


def _write_study(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "study: ai26",
                "timezone: UTC",
                "window:",
                "  start: '2026-09-01'",
                "  end: '2026-12-31'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _mirror(tmp_path: Path, monkeypatch) -> tuple[ai26_browser.JsonlDistributedMirror, DistributedCaptureSink]:
    sink = _sink(tmp_path, monkeypatch)
    monkeypatch.setattr(ai26_browser, "DistributedCaptureSink", lambda settings: sink)
    config = _write_study(tmp_path / "private" / "ai26.yaml")
    return (
        ai26_browser.JsonlDistributedMirror(
            object(),  # type: ignore[arg-type]
            study_config=config,
            data_root=tmp_path / "data",
        ),
        sink,
    )


def _write_rows(tmp_path: Path, *rows: dict) -> Path:
    normalized = tmp_path / "data" / "normalized"
    normalized.mkdir(parents=True)
    path = normalized / "x.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_url_only_row_is_refused_by_a_typed_error_naming_source_and_url(
    tmp_path: Path, monkeypatch
) -> None:
    """The refusal has to be traceable: reason, source and URL, not a bare string."""
    sink = _sink(tmp_path, monkeypatch)

    with pytest.raises(HollowRecordError) as caught:
        sink.ingest({"collection_id": "ai26", "source_url": HOLLOW_URL})

    error = caught.value
    assert error.reason == HOLLOW_RECORD_REASON
    assert error.source_url == HOLLOW_URL
    # A hollow row carries no platform, so the collection is what is left to name it by.
    assert error.source == "ai26"
    assert HOLLOW_URL in str(error)
    assert sink.records.records == []
    assert sink.objects.objects == {}
    assert sink.redis.events == []


def test_refusal_is_still_a_value_error_for_existing_callers(
    tmp_path: Path, monkeypatch
) -> None:
    sink = _sink(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="refusing hollow capture"):
        sink.ingest({"source_url": HOLLOW_URL})


def test_payload_without_text_is_accepted(tmp_path: Path, monkeypatch) -> None:
    """Not the target case: a raw body with no normalized text is still evidence."""
    sink = _sink(tmp_path, monkeypatch)
    record = CanonicalRecord(
        source_url="https://x.com/example/status/1",
        raw_capture={"payload": {"data": {"id": "1", "note_tweet": {}}}},
        content={"text": ""},
    )

    stored = sink.ingest(record.model_dump(mode="json"))

    assert stored.raw_capture.checksum.startswith("sha256:")
    assert [item.source_url for item in sink.records.records] == [stored.source_url]


def test_text_without_publication_time_is_accepted(tmp_path: Path, monkeypatch) -> None:
    """Not the target case either: the missing publication time is the handoff gate."""
    sink = _sink(tmp_path, monkeypatch)
    record = CanonicalRecord(
        source_url="https://x.com/example/status/3",
        content={"text": "a real post body"},
    )
    assert record.source.created_at is None

    stored = sink.ingest(record.model_dump(mode="json"))

    assert stored.content.text == "a real post body"
    assert sink.records.records


def test_media_reference_is_accepted(tmp_path: Path, monkeypatch) -> None:
    """A media-only capture has an addressable artefact, so it is kept."""
    sink = _sink(tmp_path, monkeypatch)
    record = CanonicalRecord(
        source_url="https://x.com/example/status/4",
        content={"media_references": [{"url": "https://pbs.example.invalid/photo.jpg"}]},
    )

    sink.ingest(record.model_dump(mode="json"))

    assert len(sink.records.records) == 1


def test_mirror_refuses_the_backlog_row_instead_of_writing_it(
    tmp_path: Path, monkeypatch
) -> None:
    """The actual writer of the 1,703 rows: a URL-only canonical JSONL line."""
    mirror, sink = _mirror(tmp_path, monkeypatch)
    _write_rows(tmp_path, {"collection_id": "ai26", "source_url": HOLLOW_URL})

    result = mirror.scan_once()

    assert result == {"scanned": 1, "synced": 0, "rejected": 1}
    assert sink.records.records == []
    assert sink.objects.objects == {}
    assert mirror.rejected_total == 1
    assert mirror.rejections == [
        {
            "source": "x.jsonl",
            "line": "0",
            "source_url": HOLLOW_URL,
            "reason": HOLLOW_RECORD_REASON,
        }
    ]
    # Reported once, not retried forever: the offset advanced past the refused row.
    assert mirror.scan_once() == {"scanned": 0, "synced": 0, "rejected": 0}


def test_mirror_does_not_wedge_on_a_bad_row_and_keeps_mirroring(
    tmp_path: Path, monkeypatch
) -> None:
    mirror, sink = _mirror(tmp_path, monkeypatch)
    keepable = CanonicalRecord(
        source_url="https://x.com/example/status/9",
        content={"text": "keepable post"},
    ).model_dump(mode="json")
    _write_rows(tmp_path, {"collection_id": "ai26", "source_url": HOLLOW_URL}, keepable)

    assert mirror.scan_once() == {"scanned": 2, "synced": 1, "rejected": 1}

    assert [item.content.text for item in sink.records.records] == ["keepable post"]
    assert mirror.rejected_total == 1


def test_mirror_rejections_are_bounded(tmp_path: Path, monkeypatch) -> None:
    mirror, _sink_instance = _mirror(tmp_path, monkeypatch)
    _write_rows(
        tmp_path,
        *[
            {"collection_id": "ai26", "source_url": f"{HOLLOW_URL}{index}"}
            for index in range(55)
        ],
    )

    result = mirror.scan_once()

    assert result == {"scanned": 55, "synced": 0, "rejected": 55}
    assert mirror.rejected_total == 55
    assert len(mirror.rejections) == 50


def test_jsonl_sync_reports_the_refusal_as_a_per_line_error(
    tmp_path: Path, monkeypatch
) -> None:
    """The other writer of hollow rows reports per line, naming the URL."""

    class StubSink:
        redis = None

        def __init__(self, settings):
            self.settings = settings

        def assert_private_config(self, path):
            return path

    settings = distributed_settings(tmp_path)
    monkeypatch.setattr(distributed_sync, "DistributedCaptureSink", StubSink)
    config = _write_study(tmp_path / "private" / "ai26.yaml")
    _write_rows(tmp_path, {"collection_id": "ai26", "source_url": HOLLOW_URL})

    report = distributed_sync.sync_normalized_records(
        settings, study_config=config, data_root=tmp_path / "data", limit=10
    )

    assert report["status"] == "partial"
    assert report["synced"] == 0
    assert report["scanned"] == 1
    assert len(report["errors"]) == 1
    assert report["errors"][0].startswith("x.jsonl:1:")
    assert HOLLOW_URL in report["errors"][0]


def test_laskin_cycle_reports_the_refusal_against_its_source(
    monkeypatch, tmp_path: Path
) -> None:
    """A refused capture is a per-source error, never a silent skip or a success."""

    class Sink:
        notification_errors: list[str] = []

        def __init__(self, settings):
            pass

        def assert_private_config(self, path):
            pass

        def ingest_with_status(self, payload):
            # Mirror the real sink: validate the canonical fields, then refuse with the
            # same typed error.
            canonical = CanonicalRecord.model_validate(
                {key: value for key, value in payload.items() if key in CanonicalRecord.model_fields}
            )
            if not (
                str(canonical.content.text or "").strip()
                or canonical.raw_capture.preserved
                or canonical.content.media_references
                or canonical.content.file_references
            ):
                raise HollowRecordError(
                    source=str(canonical.source.platform or ""),
                    source_url=str(canonical.source_url or ""),
                    collection_id=str(payload.get("collection_id") or ""),
                )
            return canonical, True

    def collect(row, **kwargs):
        return [
            NormalizedRecord(
                source_url=HOLLOW_URL,
                platform="x",
                text="",
                raw_capture={"payload": None},
                collection_provenance=CollectionProvenance(module="test"),
            )
        ], []

    jobs = [{"kind": "web_source", "name": "x_backlog_replay", "priority": "P1"}]
    monkeypatch.setattr(runner, "DistributedCaptureSink", Sink)
    monkeypatch.setattr(runner, "load_non_browser_jobs", lambda path: jobs)
    monkeypatch.setattr(runner, "preflight_optional_dependencies", lambda jobs: [])
    monkeypatch.setattr(runner, "_records_for_job", collect)
    monkeypatch.setattr(
        runner,
        "run_phase1_rss",
        lambda *args, **kwargs: {"records_synced": 0, "records_new": 0},
    )

    report = runner.run_phase1_laskin(
        Settings(_env_file=None, project_id="ai26"),
        study_config=tmp_path / "study.yaml",
        source_manifest=tmp_path / "sources.toml",
        rotation=0,
        limit=20,
        max_jobs=4,
        per_source_limit=5,
    )

    outcome = report["source_outcomes"][0]
    assert outcome["name"] == "x_backlog_replay"
    assert outcome["status"] == "error"
    assert outcome["reason"] == HOLLOW_RECORD_REASON
    assert outcome["records_synced"] == 0
    assert report["non_browser_records_synced"] == 0
    assert report["status"] == "partial"
    assert any(
        "x_backlog_replay" in error and HOLLOW_URL in error for error in report["errors"]
    )
