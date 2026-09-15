"""Compatibility facade for composable Collection deployment profiles.

New code should use :mod:`laclaugpt_data_collection.deployment`. These helpers
preserve the small profile API introduced concurrently on ``main``.
"""
from __future__ import annotations

from pathlib import Path

from .deployment import DeploymentProfile as RuntimeProfile


def laptop(root: str | Path = "data") -> RuntimeProfile:
    del root
    return RuntimeProfile.laptop_firefox_local()


def linux_server(
    root: str | Path = "data",
    storage: str = "local",
) -> RuntimeProfile:
    del root
    if storage == "distributed":
        return RuntimeProfile.linux_server_distributed()
    if storage == "local":
        return RuntimeProfile.linux_server_local()
    raise ValueError("storage must be 'local' or 'distributed'")


DeploymentProfile = RuntimeProfile

__all__ = ["DeploymentProfile", "laptop", "linux_server"]
