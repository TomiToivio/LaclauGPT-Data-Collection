"""Shared Redis/MongoDB/S3 namespace derivation for distributed LaclauGPT projects."""
from __future__ import annotations

import re
from dataclasses import dataclass

_PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_MONGO_KINDS = {"records", "annotations", "reviews", "runs", "artifacts"}
_S3_KINDS = {
    "raw",
    "canonical",
    "media",
    "transcripts",
    "frames",
    "analysis",
    "codebooks",
    "manifests",
    "exports",
    "runs",
}
_MODULES = {"collection", "analysis", "visualization"}


def validate_project_id(project_id: str) -> str:
    """Validate without silently rewriting research project identity."""
    if not _PROJECT_ID.fullmatch(project_id):
        raise ValueError(
            "project_id must match ^[a-z0-9][a-z0-9_-]{1,63}$; "
            "examples: ai26, ep24, brazil26, hungary26"
        )
    return project_id


def _segment(value: str, *, label: str) -> str:
    value = value.strip("/")
    if not value or value in {".", ".."} or "/../" in f"/{value}/":
        raise ValueError(f"invalid {label}: {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class ProjectNamespace:
    """Derive collision-safe names shared by every LaclauGPT module."""

    project_id: str
    redis_prefix: str = "laclaugpt"
    mongo_database: str = "laclaugpt"
    mongo_separator: str = "__"
    s3_prefix_root: str = "projects"

    def __post_init__(self) -> None:
        validate_project_id(self.project_id)
        _segment(self.redis_prefix, label="redis_prefix")
        _segment(self.mongo_database, label="mongo_database")
        _segment(self.s3_prefix_root, label="s3_prefix_root")
        if not self.mongo_separator:
            raise ValueError("mongo_separator must not be empty")

    @property
    def redis_base(self) -> str:
        return f"{self.redis_prefix}:{self.project_id}"

    def redis_key(self, *parts: str) -> str:
        safe = [_segment(part, label="redis key segment") for part in parts]
        return ":".join((self.redis_base, *safe))

    def manifest_key(self, revision: str = "current") -> str:
        return self.redis_key("manifest", revision)

    def settings_key(self, module: str, revision: str = "current") -> str:
        if module not in _MODULES:
            raise ValueError(f"unknown module: {module}")
        return self.redis_key("settings", module, revision)

    def codebook_key(self, name: str, revision: str = "current") -> str:
        return self.redis_key("codebook", name, revision)

    def stream_key(self, name: str) -> str:
        return self.redis_key("stream", name)

    def worker_key(self, module: str, worker_id: str) -> str:
        if module not in _MODULES:
            raise ValueError(f"unknown module: {module}")
        return self.redis_key("worker", module, worker_id)

    def mongo_collection(self, kind: str) -> str:
        if kind not in _MONGO_KINDS:
            raise ValueError(f"unknown MongoDB collection kind: {kind}")
        return f"{self.project_id}{self.mongo_separator}{kind}"

    def s3_key(self, kind: str, *parts: str) -> str:
        if kind not in _S3_KINDS:
            raise ValueError(f"unknown S3 object kind: {kind}")
        safe = [_segment(part, label="S3 key segment") for part in parts]
        prefix = f"{self.s3_prefix_root}/{self.project_id}/{kind}"
        return "/".join((prefix, *safe)) if safe else f"{prefix}/"

    def s3_uri(self, bucket: str, kind: str, *parts: str) -> str:
        return f"s3://{_segment(bucket, label='bucket')}/{self.s3_key(kind, *parts)}"
