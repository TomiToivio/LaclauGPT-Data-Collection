import json
from pathlib import Path

import pytest

from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.deployment import DeploymentProfile, apply_profile, validate_profile
from laclaugpt_data_collection.distributed_capture import DistributedCaptureSink
from laclaugpt_data_collection.models import CanonicalRecord


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


def distributed_settings(tmp_path: Path) -> Settings:
    private = tmp_path / "private"
    private.mkdir()
    return apply_profile(
        Settings(
            _env_file=None,
            project_id="ai26",
            run_id="ai26-smoke-001",
            redis_url="redis://example.invalid:6379/0",
            s3_bucket="laclaugpt-test",
            private_config_dir=private,
        ),
        DeploymentProfile.laptop_firefox_distributed(),
    )


def test_distributed_profile_fails_closed_without_run_or_private_config() -> None:
    settings = apply_profile(
        Settings(_env_file=None, project_id="ai26", redis_url="redis://example.invalid", s3_bucket="x"),
        DeploymentProfile.laptop_firefox_distributed(),
    )
    problems = validate_profile(settings)
    assert any("LACLAUGPT_RUN_ID" in problem for problem in problems)
    assert any("LACLAUGPT_PRIVATE_CONFIG_DIR" in problem for problem in problems)


def test_distributed_profile_accepts_explicit_private_runtime(tmp_path: Path) -> None:
    assert validate_profile(distributed_settings(tmp_path)) == []


def test_sink_rejects_study_config_outside_private_root(tmp_path: Path, monkeypatch) -> None:
    settings = distributed_settings(tmp_path)
    monkeypatch.setattr("laclaugpt_data_collection.distributed_capture.MongoRecordStore", FakeMongo)
    monkeypatch.setattr("laclaugpt_data_collection.distributed_capture.S3ObjectStore", FakeS3)
    monkeypatch.setattr("laclaugpt_data_collection.distributed_capture.RedisCoordinator", FakeRedis)
    sink = DistributedCaptureSink(settings)
    outside = tmp_path / "public.yaml"
    outside.write_text("study: synthetic", encoding="utf-8")
    with pytest.raises(ValueError, match="PRIVATE_CONFIG_DIR"):
        sink.assert_private_config(outside)


def test_sink_writes_raw_to_s3_record_to_mongo_and_reference_event(tmp_path: Path, monkeypatch) -> None:
    settings = distributed_settings(tmp_path)
    monkeypatch.setattr("laclaugpt_data_collection.distributed_capture.MongoRecordStore", FakeMongo)
    monkeypatch.setattr("laclaugpt_data_collection.distributed_capture.S3ObjectStore", FakeS3)
    monkeypatch.setattr("laclaugpt_data_collection.distributed_capture.RedisCoordinator", FakeRedis)
    sink = DistributedCaptureSink(settings)

    record = CanonicalRecord(
        source_url="https://example.invalid/post/1?utm_source=test",
        raw_capture={"payload": {"text": "synthetic raw payload"}, "content_type": "application/json"},
        content={"text": "synthetic"},
    )
    stored = sink.ingest(record.model_dump(mode="json"))

    assert stored.source_url == "https://example.invalid/post/1"
    assert stored.raw_capture.ref.startswith("s3://laclaugpt-test/")
    assert stored.raw_capture.checksum.startswith("sha256:")
    assert sink.records.records[0].source_url == stored.source_url
    event_name, fields = sink.redis.events[0]
    assert event_name == "collected"
    assert fields["project_id"] == "ai26"
    assert fields["run_id"] == "ai26-smoke-001"
    assert fields["source_url"] == stored.source_url
    rendered = json.dumps(fields)
    assert "synthetic raw payload" not in rendered
    assert "redis://" not in rendered
