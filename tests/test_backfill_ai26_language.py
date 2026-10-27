"""Tests for the AI26 language backfill (#361).

The two defects this file pins are both of the "silent wrong answer" kind:

* a bare ``records`` collection counted zero documents, which reads exactly like
  "the defect is fixed";
* ``count_documents(limit=0)`` raises Location15958, so the first --apply run died
  before writing anything and could have been mistaken for a no-op success.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backfill_ai26_language.py"


def _module():
    spec = importlib.util.spec_from_file_location("backfill_ai26_language", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_records_live_in_a_project_namespaced_collection() -> None:
    module = _module()
    assert module.collection_name("ai26", None) == "ai26__records"


def test_project_defaults_to_ai26_when_unset(monkeypatch) -> None:
    module = _module()
    monkeypatch.delenv("LACLAUGPT_PROJECT_ID", raising=False)
    assert module.collection_name(None, None) == "ai26__records"


def test_explicit_collection_wins() -> None:
    module = _module()
    assert module.collection_name("ai26", "custom__records") == "custom__records"


def test_a_project_id_from_the_environment_is_respected(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("LACLAUGPT_PROJECT_ID", "brazil26")
    assert module.collection_name(None, None) == "brazil26__records"
