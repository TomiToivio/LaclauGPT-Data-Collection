"""Environment-first configuration with local-safe defaults.

All runtime state lives below ``data/``. The whole tree is gitignored and may
contain sensitive research material, credentials/config overlays, model caches,
logs, databases, downloaded files, and intermediate artifacts.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DATA_SUBDIRS = (
    "logs",
    "database",
    "config",
    "files",
    "csv",
    "jsonl",
    "codebooks",
    "sources",
    "downloads",
    "media",
    "models/ollama",
    "models/whisper",
    "cache",
    "tmp",
    "exports",
    "artifacts",
    "runs",
    "browser",
    "transcripts",
    "frames",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LACLAUGPT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    profile: str = "local"
    data_root: Path = Path("./data")
    sqlite_path: Path = Path("./data/database/collection.sqlite3")

    record_backend: Literal["sqlite", "mongodb"] = "sqlite"
    object_backend: Literal["filesystem", "s3"] = "filesystem"
    cache_backend: Literal["memory", "redis"] = "memory"

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "laclaugpt"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str = ""
    s3_region: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    def data_path(self, *parts: str) -> Path:
        """Return a path below the private runtime data root."""
        return self.data_root.joinpath(*parts)

    def ensure_local_directories(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        for relative in DATA_SUBDIRS:
            self.data_path(*relative.split("/")).mkdir(parents=True, exist_ok=True)
        if self.record_backend == "sqlite":
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    def safe_summary(self) -> dict[str, str]:
        """Return non-secret operational settings suitable for logs/doctor output."""
        return {
            "profile": self.profile,
            "record_backend": self.record_backend,
            "object_backend": self.object_backend,
            "cache_backend": self.cache_backend,
            "data_root": str(self.data_root),
            "sqlite_path": str(self.sqlite_path),
            "mongodb_database": self.mongodb_database,
            "s3_bucket": self.s3_bucket,
        }
