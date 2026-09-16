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
            redis_url="redis://example.invalid:6379/0",
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
