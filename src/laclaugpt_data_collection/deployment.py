"""Composable machine/execution/storage/browser deployment helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Settings


@dataclass(frozen=True)
class DeploymentProfile:
    machine: str
    execution: str
    storage: str
    browser: str

    @classmethod
    def laptop_firefox_local(cls) -> "DeploymentProfile":
        return cls("laptop", "cli", "local", "firefox-local")

    @classmethod
    def laptop_firefox_distributed(cls) -> "DeploymentProfile":
        return cls("laptop", "cli", "distributed", "firefox-local")

    @classmethod
    def linux_server_local(cls) -> "DeploymentProfile":
        return cls("linux-server", "cron", "local", "none")

    @classmethod
    def linux_server_distributed(cls) -> "DeploymentProfile":
        return cls("linux-server", "cron", "distributed", "none")

    def settings_overrides(self) -> dict[str, str]:
        if self.storage == "distributed":
            records, objects, cache = "mongodb", "s3", "redis"
        else:
            records, objects, cache = "sqlite", "filesystem", "memory"
        return {
            "machine": self.machine,
            "execution": self.execution,
            "browser": self.browser,
            "record_backend": records,
            "object_backend": objects,
            "cache_backend": cache,
        }


def apply_profile(settings: Settings, profile: DeploymentProfile) -> Settings:
    """Return a validated Settings copy with deployment dimensions applied."""
    return settings.model_copy(update=profile.settings_overrides())


def validate_profile(settings: Settings) -> list[str]:
    """Return validation warnings/errors without contacting external services."""
    problems: list[str] = []
    if settings.browser == "firefox-local" and settings.browser_host not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        problems.append("firefox-local browser capture must bind to localhost")
    if settings.record_backend == "mongodb" and not settings.mongodb_uri:
        problems.append("distributed records require a MongoDB URI")
    redis_requested = (
        settings.cache_backend == "redis"
        or settings.distributed_config_backend == "redis"
        or settings.messaging_backend == "redis"
        or settings.task_queue_backend == "redis"
    )
    if redis_requested and not settings.redis_url:
        problems.append("Redis features require LACLAUGPT_REDIS_URL")
    if settings.object_backend == "s3" and not settings.s3_bucket:
        problems.append("S3 object storage requires a bucket")
    if settings.distributed_requested:
        if not settings.run_id:
            problems.append("distributed collection requires LACLAUGPT_RUN_ID")
        if settings.project_id == "default":
            problems.append("distributed collection requires an explicit LACLAUGPT_PROJECT_ID")
        if settings.private_config_dir is None:
            problems.append("distributed collection requires LACLAUGPT_PRIVATE_CONFIG_DIR")
        elif not settings.private_config_dir.is_dir():
            problems.append("LACLAUGPT_PRIVATE_CONFIG_DIR must point to an existing directory")
    return problems


def render_cron(command: str, *, schedule: str = "17 * * * *") -> str:
    """Render a safe cron line. It does not install or execute anything."""
    return f"{schedule} flock -n data/runs/collection.lock {command} >> data/logs/collection.log 2>&1"


def render_systemd_units(
    command: str, *, working_directory: Path = Path("/opt/laclaugpt-collection")
) -> dict[str, str]:
    """Render placeholder service/timer units without touching systemd."""
    service = f"""[Unit]\nDescription=LaclauGPT Collection\n\n[Service]\nType=oneshot\nWorkingDirectory={working_directory}\nExecStart={command}\n"""
    timer = """[Unit]\nDescription=Run LaclauGPT Collection hourly\n\n[Timer]\nOnCalendar=hourly\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n"""
    return {"service": service, "timer": timer}
