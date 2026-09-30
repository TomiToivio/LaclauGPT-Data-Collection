"""Regression tests for issue #197: the unset-project-id state must be detectable.

Background. ``Settings.project_id`` used to default to ``"default"``, and several
call sites treated the literal string ``"default"`` as meaning "the operator did
not configure a study". Commit ``07c309b`` moved the global default to ``"ai26"``
without updating those comparisons, so each of them silently stopped recognising
the unset state:

- ``brazil26_browser._brazil26_settings`` no longer overrode an ambient project
  id, so a Brazil26 run on a host whose ``.env`` carried the new AI26 default
  failed its own fail-closed check with a message that blamed the study config.
- ``ai26_browser._ai26_settings`` carried the identical stale comparison.
- ``deployment.validate_profile`` stopped requiring an explicit project id for
  distributed runs entirely, i.e. it failed *open*.

These tests pin the corrected behaviour, which is derived from the unset state
rather than from any hard-coded sentinel, so it survives a future default change.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from laclaugpt_data_collection import ai26_browser, brazil26_browser, deployment
from laclaugpt_data_collection.config import (
    Settings,
    project_id_was_explicitly_configured,
)


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """Run in a scratch cwd with no ambient project/run id in the environment."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LACLAUGPT_PROJECT_ID", raising=False)
    monkeypatch.delenv("LACLAUGPT_RUN_ID", raising=False)
    monkeypatch.delenv("LACLAUGPT_RECORD_BACKEND", raising=False)
    monkeypatch.delenv("LACLAUGPT_MONGODB_URI", raising=False)
    return tmp_path


def _ambient_dotenv(tmp_path: Path, body: str) -> None:
    (tmp_path / ".env").write_text(body, encoding="utf-8")


# --------------------------------------------------------------- the helper

def test_helper_distinguishes_default_from_explicit(clean_env, monkeypatch) -> None:
    """The whole fix rests on this distinction, so assert it directly."""
    assert project_id_was_explicitly_configured(Settings(_env_file=None)) is False

    monkeypatch.setenv("LACLAUGPT_PROJECT_ID", "ai26")
    assert project_id_was_explicitly_configured(Settings(_env_file=None)) is True

    # The new default is still a *default*: equality with it is not evidence
    # that anyone configured it.
    monkeypatch.setenv("LACLAUGPT_PROJECT_ID", "default")
    settings = Settings(_env_file=None)
    assert settings.project_id == "default"
    assert project_id_was_explicitly_configured(settings) is True


def test_helper_ignores_an_ambient_dotenv_when_env_file_is_disabled(
    clean_env, monkeypatch
) -> None:
    _ambient_dotenv(clean_env, "LACLAUGPT_PROJECT_ID=ai26\n")
    settings = Settings(_env_file=None)
    assert project_id_was_explicitly_configured(settings) is False


def test_helper_sees_an_explicit_env_file(clean_env) -> None:
    explicit = clean_env / "explicit.env"
    explicit.write_text("LACLAUGPT_PROJECT_ID=from-file\n", encoding="utf-8")
    settings = Settings(_env_file=explicit)
    assert settings.project_id == "from-file"
    assert project_id_was_explicitly_configured(settings) is True


# ------------------------------------------------------- brazil26 guard

def test_brazil26_overrides_the_ambient_ai26_default(clean_env) -> None:
    """The reported #197 failure, exactly: ambient .env carries the new default."""
    _ambient_dotenv(
        clean_env, "LACLAUGPT_PROJECT_ID=ai26\nLACLAUGPT_RUN_ID=ambient-dotenv\n"
    )
    settings = brazil26_browser._brazil26_settings(env_file=None)
    assert settings.project_id == "brazil26"
    assert settings.run_id.startswith("brazil26-browser-")
    assert settings.run_id != "ambient-dotenv"


def test_brazil26_still_refuses_an_explicitly_configured_other_study(
    clean_env, monkeypatch
) -> None:
    """The fail-closed guard must not be weakened by the fix."""
    monkeypatch.setenv("LACLAUGPT_PROJECT_ID", "ai26")
    with pytest.raises(ValueError, match="must be 'brazil26'"):
        brazil26_browser._brazil26_settings(env_file=None)


def test_brazil26_accepts_its_own_explicit_id(clean_env, monkeypatch) -> None:
    monkeypatch.setenv("LACLAUGPT_PROJECT_ID", "brazil26")
    assert brazil26_browser._brazil26_settings(env_file=None).project_id == "brazil26"


# ----------------------------------------------------------- ai26 guard

def test_ai26_defaults_when_nothing_is_configured(clean_env) -> None:
    assert ai26_browser._ai26_settings(env_file=None).project_id == "ai26"


def test_ai26_refuses_an_explicitly_configured_other_study(
    clean_env, monkeypatch
) -> None:
    monkeypatch.setenv("LACLAUGPT_PROJECT_ID", "brazil26")
    with pytest.raises(ValueError, match="must be 'ai26'"):
        ai26_browser._ai26_settings(env_file=None)


def test_ai26_does_not_inherit_an_ambient_ai26_dotenv_unset_semantics(
    clean_env, monkeypatch
) -> None:
    """An ambient dotenv is ignored, so the id still falls back to the study's own."""
    _ambient_dotenv(clean_env, "LACLAUGPT_PROJECT_ID=ai26\n")
    monkeypatch.setenv("LACLAUGPT_PROJECT_ID", "ai26")
    assert ai26_browser._ai26_settings(env_file=None).project_id == "ai26"


# ---------------------------------------------------------- deployment

def test_distributed_run_requires_an_explicit_project_id(
    clean_env, monkeypatch
) -> None:
    """Previously failed open: ``== \"default\"`` matched nothing once the default moved."""
    monkeypatch.setenv("LACLAUGPT_RECORD_BACKEND", "mongodb")
    settings = Settings(_env_file=None)
    assert settings.distributed_requested is True
    problems = deployment.validate_profile(settings)
    assert any("PROJECT_ID" in p for p in problems), problems


def test_distributed_run_accepts_an_explicit_project_id(clean_env, monkeypatch) -> None:
    monkeypatch.setenv("LACLAUGPT_RECORD_BACKEND", "mongodb")
    monkeypatch.setenv("LACLAUGPT_PROJECT_ID", "ai26")
    settings = Settings(_env_file=None)
    problems = deployment.validate_profile(settings)
    assert not [p for p in problems if "PROJECT_ID" in p], problems
