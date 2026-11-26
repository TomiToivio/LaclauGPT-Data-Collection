"""#478: a queue-dispatched localhost cycle may not write a local-only corpus."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import laclaugpt_data_collection.ai26_localhost_collect as localhost
from laclaugpt_data_collection.ai26_localhost_collect import collect_manifest


class _Dispatch:
    """The guard must fire before the dispatch object is queried."""


def _settings(monkeypatch) -> None:
    monkeypatch.setattr(
        localhost, "Settings", lambda: SimpleNamespace(mongodb_uri="", record_backend="auto")
    )


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    manifest = tmp_path / "sources.toml"
    manifest.write_text("", encoding="utf-8")
    study = tmp_path / "ai26.yaml"
    study.write_text("collection_policy:\n  publication_date_floor: 2026-09-01\n", encoding="utf-8")
    return manifest, study


def test_a_dispatched_cycle_refuses_to_fall_back_to_local_storage(tmp_path, monkeypatch):
    _settings(monkeypatch)
    manifest, study = _inputs(tmp_path)

    with pytest.raises(ValueError, match="requires LACLAUGPT_MONGODB_URI"):
        collect_manifest(manifest, study, dispatch=cast(Any, _Dispatch()))


def test_the_refusal_names_the_shared_corpus_requirement(tmp_path, monkeypatch):
    """The error must say why, or the next operator reads it as a broken install."""
    _settings(monkeypatch)
    manifest, study = _inputs(tmp_path)

    with pytest.raises(ValueError) as raised:
        collect_manifest(manifest, study, dispatch=cast(Any, _Dispatch()))

    message = str(raised.value)
    assert "shared AI26 collection" in message
    assert "local storage" in message
