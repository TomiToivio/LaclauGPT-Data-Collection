# -*- coding: utf-8 -*-
"""Issue #233 criteria 3 and 5 — a verified Allas upload with actionable diagnostics.

Criterion 3: an upload's object key and processing state are recorded durably, and a
rerun is idempotent. Criterion 5: credential expiry, network outage and
inaccessible-media cases must "fail safely, surface actionable diagnostics and can be
retried without duplicate records".

The mechanism that makes unattended cron diagnosable is a *stable reason token*: an
expired CSC Allas token, a wrong bucket, a transport blip and a truncated body need
different remedies, and a log reader must be able to tell them apart without parsing a
vendor message. A bare `put_object` that returns without raising also proves only that
the request was accepted -- so the object is read back and its size compared.
"""
from __future__ import annotations

import pytest

from laclaugpt_data_collection.storage.remote import (
    ObjectStoreError,
    S3ObjectStore,
    classify_object_store_failure,
)


def _client_error(code: str, *, status: int = 400) -> Exception:
    exc = Exception(f"An error occurred ({code}) when calling the PutObject operation")
    exc.response = {  # type: ignore[attr-defined]
        "Error": {"Code": code},
        "ResponseMetadata": {"HTTPStatusCode": status},
    }
    return exc


class FakeClient:
    """A minimal S3 stand-in: records puts, and can be told to misbehave."""

    def __init__(self, *, put_error: Exception | None = None, head_error: Exception | None = None,
                 reported_size: int | None = None) -> None:
        self.puts: list[dict] = []
        self._put_error = put_error
        self._head_error = head_error
        self._reported_size = reported_size

    def put_object(self, **kwargs):
        if self._put_error is not None:
            raise self._put_error
        self.puts.append(kwargs)
        return {"ETag": '"x"'}

    def head_object(self, **kwargs):
        if self._head_error is not None:
            raise self._head_error
        size = self._reported_size
        if size is None:
            size = len(self.puts[-1]["Body"])
        return {"ContentLength": size}


def _store(client: FakeClient) -> S3ObjectStore:
    store = S3ObjectStore.__new__(S3ObjectStore)
    store.bucket = "brazil26-media"
    store.prefix = "brazil26"
    store.signature_version = "s3"
    store.addressing_style = "auto"
    store._client = client
    return store


class TestVerifiedUpload:
    """A put that returns is not proof that the object exists."""

    def test_a_successful_upload_is_verified_and_returns_the_uri(self) -> None:
        client = FakeClient()
        uri = _store(client).put_bytes("media/abc.mp4", b"video-bytes", content_type="video/mp4")
        assert uri == "s3://brazil26-media/brazil26/media/abc.mp4"
        assert client.puts[0]["Key"] == "brazil26/media/abc.mp4"

    def test_a_truncated_upload_is_caught_not_accepted(self) -> None:
        """Ceph can accept a short body; the object must match what was sent."""
        client = FakeClient(reported_size=3)
        with pytest.raises(ObjectStoreError) as excinfo:
            _store(client).put_bytes("media/abc.mp4", b"video-bytes")
        assert excinfo.value.reason == "truncated_upload"
        assert "sent 11 bytes" in str(excinfo.value)

    def test_a_missing_object_after_put_is_not_reported_as_success(self) -> None:
        client = FakeClient(head_error=_client_error("NoSuchKey", status=404))
        with pytest.raises(ObjectStoreError) as excinfo:
            _store(client).put_bytes("media/abc.mp4", b"x")
        assert excinfo.value.reason == "object_missing"

    def test_verification_can_be_skipped_explicitly(self) -> None:
        class NoHead(FakeClient):
            def head_object(self, **kwargs):  # pragma: no cover - must never be called
                raise AssertionError("verify=False must not issue a HeadObject")

        client = NoHead()
        assert _store(client).put_bytes("k", b"x", verify=False).startswith("s3://")

    def test_the_prefix_is_applied_to_both_the_put_and_the_verification(self) -> None:
        """A verify against the unprefixed key would pass while the object is absent."""
        seen: list[str] = []

        class Recorder(FakeClient):
            def head_object(self, **kwargs):
                seen.append(kwargs["Key"])
                return super().head_object(**kwargs)

        client = Recorder()
        _store(client).put_bytes("media/abc.mp4", b"x")
        assert seen == ["brazil26/media/abc.mp4"]


class TestActionableDiagnostics:
    """The remedy differs per failure class, so the class must survive to the log."""

    @pytest.mark.parametrize(
        ("code", "status", "expected"),
        [
            ("ExpiredToken", 400, "credential_expired"),
            ("TokenRefreshRequired", 400, "credential_expired"),
            ("InvalidAccessKeyId", 403, "credential_rejected"),
            ("SignatureDoesNotMatch", 403, "credential_rejected"),
            ("AccessDenied", 403, "credential_rejected"),
            ("NoSuchBucket", 404, "bucket_or_prefix_wrong"),
            ("NoSuchKey", 404, "object_missing"),
            ("SlowDown", 503, "transient_transport"),
        ],
    )
    def test_each_failure_class_maps_to_its_own_reason(self, code, status, expected) -> None:
        assert classify_object_store_failure(_client_error(code, status=status)) == expected

    def test_a_transport_timeout_is_transient_and_retryable(self) -> None:
        assert classify_object_store_failure(TimeoutError("read timed out")) == "transient_transport"

    def test_an_unrecognised_failure_is_not_claimed_to_be_something_it_is_not(self) -> None:
        assert classify_object_store_failure(Exception("weird")) == "unknown"

    def test_a_failed_upload_raises_with_the_reason_attached(self) -> None:
        client = FakeClient(put_error=_client_error("ExpiredToken"))
        with pytest.raises(ObjectStoreError) as excinfo:
            _store(client).put_bytes("media/abc.mp4", b"x")
        assert excinfo.value.reason == "credential_expired"
        assert "brazil26/media/abc.mp4" in str(excinfo.value)

    def test_the_expiry_case_is_distinguishable_from_a_wrong_bucket(self) -> None:
        """The whole point: an operator renews a token OR fixes a bucket, not both."""
        expired = classify_object_store_failure(_client_error("ExpiredToken"))
        wrong_bucket = classify_object_store_failure(_client_error("NoSuchBucket", status=404))
        assert expired != wrong_bucket

    def test_the_original_exception_is_preserved_as_the_cause(self) -> None:
        original = _client_error("ExpiredToken")
        client = FakeClient(put_error=original)
        with pytest.raises(ObjectStoreError) as excinfo:
            _store(client).put_bytes("k", b"x")
        assert excinfo.value.__cause__ is original
