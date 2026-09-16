"""Environment-first configuration with local-safe defaults.

All runtime state lives below ``data/``. The whole tree is gitignored and may
contain sensitive research material, credentials/config overlays, model caches,
logs, databases, downloaded files, and intermediate artifacts.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from .distributed import ProjectNamespace

DATA_SUBDIRS = (
    "logs", "database", "config", "files", "csv", "jsonl", "codebooks", "sources",
    "downloads", "media", "models/ollama", "models/whisper", "cache", "tmp", "exports",
    "artifacts", "runs", "browser", "transcripts", "frames",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LACLAUGPT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    project_id: str = "default"
    run_id: str = ""
    profile: str = "local"
    machine: Literal["laptop", "linux-server", "custom"] = "laptop"
    execution: Literal["cli", "cron", "systemd", "agent", "custom"] = "cli"
    browser: Literal["firefox-local", "worker", "none", "custom"] = "firefox-local"
    caller: str = "human-cli"
    private_config_dir: Path | None = None

    data_root: Path = Path("./data")
    sqlite_path: Path = Path("./data/database/collection.sqlite3")
    csv_path: Path = Path("./data/csv/records.csv")

    # auto is the preferred deployment contract: MongoDB is considered only when
    # explicitly configured; otherwise collection stays entirely local in CSV.
    # sqlite remains supported for backwards compatibility with existing deployments.
    record_backend: Literal["auto", "csv", "sqlite", "mongodb"] = "auto"
    object_backend: Literal["filesystem", "s3"] = "filesystem"
    cache_backend: Literal["memory", "redis"] = "memory"

    messaging_backend: Literal["none", "redis"] = "none"
    task_queue_backend: Literal["direct", "redis"] = "direct"

    browser_host: str = "127.0.0.1"
    browser_port: int = 8765

    # Empty by default so auto mode never sends data to an unconfigured service.
    mongodb_uri: str = ""
    mongodb_database: str = "laclaugpt"
    mongodb_collection: str = ""
    mongodb_connect_timeout_ms: int = 2000
    mongodb_graph_max_depth: int = 3

    redis_url: str = ""
    redis_key_prefix: str = "laclaugpt"

    s3_endpoint: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = ""
    s3_bucket: str = ""
    s3_prefix_root: str = "projects"
    s3_access_key: str = ""
    s3_access_key_id: str = ""
    s3_secret_key: str = ""
    s3_secret_access_key: str = ""

    rag_enabled: bool = False
    rag_backend: Literal["none", "neo4j", "queue", "custom"] = "none"
    rag_dataset: str = ""
    rag_failure_log: Path = Path("./data/logs/rag-index-failures.jsonl")
    neo4j_uri: str = ""
    neo4j_database: str = "neo4j"
    neo4j_user: str = ""
    neo4j_password: str = ""
    embedding_provider: Literal["none", "ollama", "remote", "custom"] = "none"
    embedding_endpoint: str = ""
    embedding_model: str = ""

    @property
    def effective_s3_endpoint(self) -> str:
        return self.s3_endpoint or self.s3_endpoint_url

    @property
    def effective_s3_access_key(self) -> str:
        return self.s3_access_key or self.s3_access_key_id

    @property
    def effective_s3_secret_key(self) -> str:
        return self.s3_secret_key or self.s3_secret_access_key

    @property
    def distributed_namespace(self) -> ProjectNamespace:
        return ProjectNamespace(
            project_id=self.project_id,
            redis_prefix=self.redis_key_prefix,
            mongo_database=self.mongodb_database,
            s3_prefix_root=self.s3_prefix_root,
        )

    @property
    def effective_mongodb_collection(self) -> str:
        return self.mongodb_collection or self.distributed_namespace.mongo_collection("records")

    @property
    def distributed_requested(self) -> bool:
        return (
            self.record_backend == "mongodb"
            or (self.record_backend == "auto" and bool(self.mongodb_uri))
            or self.object_backend == "s3"
            or self.cache_backend == "redis"
            or self.messaging_backend == "redis"
            or self.task_queue_backend == "redis"
        )

    def data_path(self, *parts: str) -> Path:
        return self.data_root.joinpath(*parts)

    def ensure_local_directories(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        for relative in DATA_SUBDIRS:
            self.data_path(*relative.split("/")).mkdir(parents=True, exist_ok=True)
        if self.record_backend in {"sqlite", "auto", "csv"}:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        if self.rag_enabled:
            self.rag_failure_log.parent.mkdir(parents=True, exist_ok=True)

    def safe_summary(self) -> dict[str, str]:
        namespace = self.distributed_namespace
        return {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "profile": self.profile,
            "machine": self.machine,
            "execution": self.execution,
            "browser": self.browser,
            "caller": self.caller,
            "record_backend": self.record_backend,
            "object_backend": self.object_backend,
            "cache_backend": self.cache_backend,
            "messaging_backend": self.messaging_backend,
            "task_queue_backend": self.task_queue_backend,
            "data_root": str(self.data_root),
            "sqlite_path": str(self.sqlite_path),
            "csv_path": str(self.csv_path),
            "private_config_dir_configured": str(self.private_config_dir is not None),
            "redis_namespace": namespace.redis_base,
            "mongodb_configured": str(bool(self.mongodb_uri)),
            "mongodb_database": self.mongodb_database,
            "mongodb_records_collection": self.effective_mongodb_collection,
            "s3_bucket": self.s3_bucket,
            "s3_project_prefix": namespace.s3_key("raw"),
            "browser_host": self.browser_host,
            "browser_port": str(self.browser_port),
            "rag_enabled": str(self.rag_enabled),
            "rag_backend": self.rag_backend,
            "rag_dataset": self.rag_dataset,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
        }
