from laclaugpt_data_collection.distributed_media_runner import (
    S3MediaBackend,
    apply_media_results,
)
from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.media import MediaJob


class FakeObjectStore:
    def __init__(self):
        self.calls = []

    def put_bytes(self, key, payload, *, content_type="application/octet-stream"):
        self.calls.append((key, payload, content_type))
        return f"s3://bucket/projects/ai26/{key}"


def record() -> dict:
    return {
        "collection_id": "ai26",
        "source_url": "https://example.invalid/post/1",
        "source": {"platform": "instagram", "created_at": "2026-09-16T10:00:00Z"},
        "content": {
            "text": "synthetic",
            "media_references": [
                {
                    "kind": "image",
                    "url": "https://media.example.invalid/image.jpg",
                    "media_index": 0,
                }
            ],
        },
        "provenance": [{"metadata": {"collection_id": "ai26"}}],
    }


def test_s3_backend_places_media_below_media_prefix() -> None:
    store = FakeObjectStore()
    backend = S3MediaBackend(store)
    uri = backend.save("abc/image.jpg", b"pixels", "image/jpeg")
    assert uri.endswith("/media/abc/image.jpg")
    assert store.calls == [("media/abc/image.jpg", b"pixels", "image/jpeg")]


def test_completed_media_result_makes_canonical_record_analysis_ready() -> None:
    value = record()
    before = build_handoff(value, project_id="ai26")
    assert before["status"] == "waiting_media"

    jobs = [
        MediaJob(
            media_key="ai26:instagram:abc:0",
            collection_id="ai26",
            platform="instagram",
            source_id=value["source_url"],
            media_index=0,
            kind="image",
            url="https://media.example.invalid/image.jpg",
        )
    ]
    results = [
        {
            "media_key": jobs[0].media_key,
            "collection_id": "ai26",
            "status": "completed",
            "local_path": "s3://bucket/projects/ai26/media/abc/image.jpg",
            "sha256": "abc123",
            "byte_size": 42,
            "mime_type": "image/jpeg",
        }
    ]
    touched = apply_media_results([value], jobs, results, default_collection="ai26")
    assert touched == [value]
    ref = value["content"]["media_references"][0]
    assert ref["object_ref"].startswith("s3://")
    assert ref["checksum"] == "abc123"
    assert ref["metadata"]["download_status"] == "completed"

    after = build_handoff(value, project_id="ai26")
    assert after["status"] == "ready"
    assert after["reason"] == "media_ready"


def test_failed_media_does_not_touch_record() -> None:
    value = record()
    job = MediaJob(
        media_key="ai26:instagram:abc:0",
        collection_id="ai26",
        platform="instagram",
        source_id=value["source_url"],
        media_index=0,
        kind="image",
        url="https://media.example.invalid/image.jpg",
    )
    touched = apply_media_results(
        [value],
        [job],
        [{"media_key": job.media_key, "status": "failed"}],
        default_collection="ai26",
    )
    assert touched == []
    assert "object_ref" not in value["content"]["media_references"][0]
