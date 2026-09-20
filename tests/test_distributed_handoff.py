from pathlib import Path

from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.deployment import DeploymentProfile, apply_profile
from laclaugpt_data_collection.distributed_capture import DistributedCaptureSink


class FakeMongo:
    def __init__(self, uri, database, collection, project_id):
        self.records = []

    def upsert(self, record):
        self.records.append(record)


class FakeS3:
    def __init__(self, *, bucket, prefix, **kwargs):
        self.bucket = bucket
        self.prefix = prefix

    def put_bytes(self, key, payload, *, content_type="application/octet-stream"):
        return f"s3://{self.bucket}/{self.prefix}/{key}"


class FakeRedis:
    def __init__(self, url, namespace):
        self.events = []

    def ping(self):
        return True

    def publish_stream(self, name, fields, *, maxlen=100000):
        self.events.append((name, fields))
        return "1-0"


def settings(tmp_path: Path) -> Settings:
    private = tmp_path / "private"
    private.mkdir()
    return apply_profile(
        Settings(
            _env_file=None,
            project_id="ai26",
            run_id="ai26-smoke-ready",
            mongodb_uri="mongodb://example.invalid:27017",
            redis_url="redis://example.invalid:6379/0",
            messaging_backend="redis",
            s3_bucket="synthetic",
            private_config_dir=private,
        ),
        DeploymentProfile.laptop_firefox_distributed(),
    )


def patch_backends(monkeypatch) -> None:
    monkeypatch.setattr("laclaugpt_data_collection.distributed_capture.MongoRecordStore", FakeMongo)
    monkeypatch.setattr("laclaugpt_data_collection.distributed_capture.S3ObjectStore", FakeS3)
    monkeypatch.setattr("laclaugpt_data_collection.distributed_capture.RedisCoordinator", FakeRedis)


def test_ready_ai26_record_emits_reference_only_analysis_event(tmp_path: Path, monkeypatch) -> None:
    patch_backends(monkeypatch)
    sink = DistributedCaptureSink(settings(tmp_path))
    sink.ingest(
        {
            "collection_id": "ai26",
            "source_url": "https://example.invalid/post/ready",
            "source": {"platform": "rss", "created_at": "2026-09-16T10:00:00Z"},
            "content": {"text": "synthetic text-only source"},
            "raw_capture": {"payload": {"raw": "large source payload"}},
        }
    )
    assert [name for name, _ in sink.redis.events] == ["collected", "analysis-ready"]
    _, event = sink.redis.events[-1]
    assert event["collection_id"] == "ai26"
    assert event["source_priority"] == "1"
    assert len(event["revision"]) == 64
    assert len(event["handoff_key"]) == 64
    assert "large source payload" not in repr(event)


def test_media_record_does_not_emit_ready_event_before_download(tmp_path: Path, monkeypatch) -> None:
    patch_backends(monkeypatch)
    sink = DistributedCaptureSink(settings(tmp_path))
    sink.ingest(
        {
            "collection_id": "ai26",
            "source_url": "https://example.invalid/post/media",
            "source": {"platform": "instagram", "created_at": "2026-09-16T10:00:00Z"},
            "content": {
                "text": "synthetic media source",
                "media_references": [
                    {"kind": "image", "url": "https://media.example.invalid/image.jpg"}
                ],
            },
        }
    )
    assert [name for name, _ in sink.redis.events] == ["collected"]


class FailingRedis(FakeRedis):
    def publish_stream(self, name, fields, *, maxlen=100000):
        self.events.append((name, fields))
        raise RuntimeError("synthetic redis outage")


def redis_disabled_settings(tmp_path: Path) -> Settings:
    private = tmp_path / "private-disabled"
    private.mkdir()
    return Settings(
        _env_file=None,
        project_id="ai26",
        run_id="ai26-no-redis",
        record_backend="mongodb",
        object_backend="s3",
        cache_backend="memory",
        messaging_backend="none",
        mongodb_uri="mongodb://example.invalid:27017",
        redis_url="",
        s3_bucket="synthetic",
        private_config_dir=private,
    )


def test_redis_disabled_mode_persists_and_remains_pollable(tmp_path: Path, monkeypatch) -> None:
    patch_backends(monkeypatch)
    sink = DistributedCaptureSink(redis_disabled_settings(tmp_path))

    record = sink.ingest(
        {
            "collection_id": "ai26",
            "source_url": "https://example.invalid/post/no-redis",
            "source": {"platform": "rss", "created_at": "2026-09-16T10:00:00Z"},
            "content": {"text": "durable without redis"},
        }
    )

    assert sink.redis is None
    assert sink.notification_errors == []
    assert len(sink.records.records) == 1
    assert sink.records.records[0].source_url == record.source_url
    assert sink.smoke_check()["redis"] == "disabled"


def test_mongo_write_happens_before_notifications(tmp_path: Path, monkeypatch) -> None:
    trace: list[str] = []

    class OrderedMongo(FakeMongo):
        def upsert(self, record):
            trace.append("mongo")
            super().upsert(record)

    class OrderedRedis(FakeRedis):
        def publish_stream(self, name, fields, *, maxlen=100000):
            trace.append(f"redis:{name}")
            return super().publish_stream(name, fields, maxlen=maxlen)

    monkeypatch.setattr(
        "laclaugpt_data_collection.distributed_capture.MongoRecordStore", OrderedMongo
    )
    monkeypatch.setattr(
        "laclaugpt_data_collection.distributed_capture.S3ObjectStore", FakeS3
    )
    monkeypatch.setattr(
        "laclaugpt_data_collection.distributed_capture.RedisCoordinator", OrderedRedis
    )

    sink = DistributedCaptureSink(settings(tmp_path))
    sink.ingest(
        {
            "collection_id": "ai26",
            "source_url": "https://example.invalid/post/ordered",
            "source": {"platform": "rss", "created_at": "2026-09-16T10:00:00Z"},
            "content": {"text": "ordering fixture"},
        }
    )

    assert trace == ["mongo", "redis:collected", "redis:analysis-ready"]


def test_redis_event_failure_cannot_lose_durable_record(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "laclaugpt_data_collection.distributed_capture.MongoRecordStore", FakeMongo
    )
    monkeypatch.setattr(
        "laclaugpt_data_collection.distributed_capture.S3ObjectStore", FakeS3
    )
    monkeypatch.setattr(
        "laclaugpt_data_collection.distributed_capture.RedisCoordinator", FailingRedis
    )

    sink = DistributedCaptureSink(settings(tmp_path))
    record = sink.ingest(
        {
            "collection_id": "ai26",
            "source_url": "https://example.invalid/post/redis-failure",
            "source": {"platform": "rss", "created_at": "2026-09-16T10:00:00Z"},
            "content": {"text": "mongo remains authoritative"},
        }
    )

    assert len(sink.records.records) == 1
    assert sink.records.records[0].source_url == record.source_url
    assert [event[0] for event in sink.redis.events] == ["collected", "analysis-ready"]
    assert len(sink.notification_errors) == 2
