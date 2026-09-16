"""CSC Allas / S3-compatible object store client configuration.

CSC Allas is the documented distributed object-storage target. It is *not*
fully S3-compatible in two ways that silently break uploads with boto3
defaults:

1. Signature version 4 uploads are rejected with HTTP 411
   (``MissingContentLength``) even when ``Content-Length`` is sent.
2. Path-style addressing uploads are rejected with a misleading
   ``QuotaExceeded`` (HTTP 403) even when the bucket has free space. Reads
   (list/head/get) succeed with either addressing style, so the defect only
   shows up the first time an object is written.

These tests pin the constructed client to the working configuration so a later
refactor cannot silently reintroduce v4 + forced-path addressing.

They are deliberately hermetic: ``boto3`` and ``botocore.config`` are stubbed,
so the suite still runs under CI's ``pip install -e '.[dev]'`` (which does not
install the optional ``distributed`` extras).
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.factory import build_object_store
from laclaugpt_data_collection.storage.remote import S3ObjectStore


class _RecordingConfig:
    """Stand-in for botocore.config.Config that records what it was given."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.signature_version = kwargs.get("signature_version")
        self.s3 = kwargs.get("s3") or {}


class _RecordingBoto3:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def client(self, service: str, **kwargs: Any) -> object:
        self.calls.append((service, kwargs))
        return object()

    @property
    def last_config(self) -> _RecordingConfig:
        return self.calls[-1][1]["config"]


@pytest.fixture
def fake_boto3(monkeypatch: pytest.MonkeyPatch) -> _RecordingBoto3:
    """Install stub ``boto3`` and ``botocore.config`` modules for the test."""
    recorder = _RecordingBoto3()

    boto3_module = types.ModuleType("boto3")
    boto3_module.client = recorder.client  # type: ignore[attr-defined]

    botocore_module = types.ModuleType("botocore")
    config_module = types.ModuleType("botocore.config")
    config_module.Config = _RecordingConfig  # type: ignore[attr-defined]
    botocore_module.config = config_module  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "boto3", boto3_module)
    monkeypatch.setitem(sys.modules, "botocore", botocore_module)
    monkeypatch.setitem(sys.modules, "botocore.config", config_module)
    return recorder


def test_allas_defaults_use_signature_v2(fake_boto3: _RecordingBoto3) -> None:
    """Allas rejects SigV4 uploads, so SigV2 must be the default."""
    S3ObjectStore(bucket="LaclauGPT-AI26", endpoint_url="https://a3s.fi")

    service, _ = fake_boto3.calls[0]
    assert service == "s3"
    assert fake_boto3.last_config.signature_version == "s3"


def test_allas_defaults_do_not_force_path_addressing(fake_boto3: _RecordingBoto3) -> None:
    """Forced path-style addressing is what triggers the false QuotaExceeded."""
    store = S3ObjectStore(bucket="LaclauGPT-AI26", endpoint_url="https://a3s.fi")

    assert store.addressing_style == "auto"
    assert fake_boto3.last_config.s3["addressing_style"] == "auto"


def test_explicit_signature_and_addressing_are_forwarded(fake_boto3: _RecordingBoto3) -> None:
    """Operators must be able to opt back into SigV4 / path style for real AWS."""
    S3ObjectStore(
        bucket="plain-aws-bucket",
        signature_version="s3v4",
        addressing_style="path",
    )

    config = fake_boto3.last_config
    assert config.signature_version == "s3v4"
    assert config.s3["addressing_style"] == "path"


def test_endpoint_and_credentials_are_passed_through(fake_boto3: _RecordingBoto3) -> None:
    S3ObjectStore(
        bucket="LaclauGPT-AI26",
        endpoint_url="https://a3s.fi",
        region_name="regionOne",
        access_key_id="synthetic-access",
        secret_access_key="example-secret",
    )

    _, kwargs = fake_boto3.calls[0]
    assert kwargs["endpoint_url"] == "https://a3s.fi"
    assert kwargs["region_name"] == "regionOne"
    assert kwargs["aws_access_key_id"] == "synthetic-access"
    assert kwargs["aws_secret_access_key"] == "example-secret"


def test_prefix_is_normalized(fake_boto3: _RecordingBoto3) -> None:
    store = S3ObjectStore(bucket="LaclauGPT-AI26", prefix="/projects/ai26/")

    assert store.prefix == "projects/ai26"


def test_settings_default_to_allas_compatible_client() -> None:
    settings = Settings(_env_file=None)

    assert settings.s3_signature_version == "s3"
    assert settings.s3_addressing_style == "auto"


def test_settings_accept_aws_style_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LACLAUGPT_S3_SIGNATURE_VERSION", "s3v4")
    monkeypatch.setenv("LACLAUGPT_S3_ADDRESSING_STYLE", "path")

    settings = Settings(_env_file=None)

    assert settings.s3_signature_version == "s3v4"
    assert settings.s3_addressing_style == "path"


def test_settings_expose_client_configuration_in_safe_summary() -> None:
    summary = Settings(_env_file=None).safe_summary()

    assert summary["s3_signature_version"] == "s3"
    assert summary["s3_addressing_style"] == "auto"
    # The summary must never leak credentials.
    assert "s3_access_key" not in summary
    assert "s3_secret_key" not in summary


def test_factory_forwards_allas_client_configuration(fake_boto3: _RecordingBoto3) -> None:
    """The object-store factory must not drop the Allas client settings."""
    settings = Settings(
        _env_file=None,
        object_backend="s3",
        s3_bucket="LaclauGPT-AI26",
        s3_endpoint_url="https://a3s.fi",
        s3_region="regionOne",
        s3_access_key_id="synthetic-access",
        s3_secret_access_key="example-secret",
    )

    build_object_store(settings)

    config = fake_boto3.last_config
    assert config.signature_version == "s3"
    assert config.s3["addressing_style"] == "auto"
