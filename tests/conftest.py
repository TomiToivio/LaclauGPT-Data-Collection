"""Shared pytest isolation for configuration-dependent tests.

Production Settings intentionally reads .env. Tests must not inherit an
untracked developer/operator .env unless a test opts into a specific file.
"""
from __future__ import annotations

import pytest

from laclaugpt_data_collection.config import Settings


@pytest.fixture(autouse=True)
def isolate_settings_from_ambient_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable implicit .env loading for every test.

    Individual tests can still exercise dotenv loading explicitly by passing
    _env_file=<path> to Settings.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
