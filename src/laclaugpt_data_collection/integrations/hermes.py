"""Auditable agent operations for Hermes and other future agent runtimes.

These helpers call the same Settings/storage/deployment primitives as human CLI
usage. They deliberately avoid a parallel collector stack.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..deployment import validate_profile


@dataclass(frozen=True)
class RunPlan:
    caller: str
    dry_run: bool
    profile: dict[str, str]
    problems: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.problems


def inspect_effective_config(settings: Settings) -> dict[str, str]:
    """Return only the redacted/safe configuration summary."""
    return settings.safe_summary()


def validate_environment(settings: Settings) -> dict[str, Any]:
    """Validate configuration offline without contacting browsers or backends."""
    problems = validate_profile(settings)
    return {"ok": not problems, "problems": problems, "profile": settings.safe_summary()}


def plan_collection_run(settings: Settings, *, dry_run: bool = True, caller: str = "hermes-agent") -> RunPlan:
    """Plan an agent-triggered run while making provenance/caller explicit."""
    agent_settings = settings.model_copy(update={"execution": "agent", "caller": caller})
    return RunPlan(
        caller=caller,
        dry_run=dry_run,
        profile=agent_settings.safe_summary(),
        problems=tuple(validate_profile(agent_settings)),
    )


def browser_capture_readiness(settings: Settings) -> dict[str, Any]:
    """Check browser-capture configuration without opening a socket or browser."""
    problems = validate_profile(settings)
    enabled = settings.browser != "none"
    return {
        "enabled": enabled,
        "safe_local_bind": settings.browser != "firefox-local" or not problems,
        "host": settings.browser_host,
        "port": settings.browser_port,
        "problems": problems,
    }


def distributed_queue_state(settings: Settings) -> dict[str, Any]:
    """Describe queue capability without connecting to Redis in normal inspection."""
    return {
        "configured": settings.cache_backend == "redis",
        "backend": settings.cache_backend,
        "execution": settings.execution,
    }
