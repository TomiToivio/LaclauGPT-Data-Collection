"""The mirror's offset file on a filesystem that refuses an atomic rename (#378, WSL).

On the WSL/OneDrive research checkout ``Path.replace`` of the dot-temp offset file fails with
``FileNotFoundError``: a sync agent moves it between the write and the rename. That aborted every
scan after the first synced row, so the offsets stayed stale and a restart replayed the whole JSONL.
"""
from __future__ import annotations

import json
from pathlib import Path

from laclaugpt_data_collection.ai26_browser import JsonlDistributedMirror


class _Mirror:
    """The offset half of the mirror, without a sink, a study config or a network."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.state_path = data_root / ".ai26-distributed-offsets.json"
        self._offsets = {"x.jsonl": 42}


def _save(mirror: _Mirror) -> None:
    JsonlDistributedMirror._save_offsets(mirror)  # type: ignore[arg-type]


def test_offsets_are_written_atomically_when_the_rename_works(tmp_path: Path) -> None:
    mirror = _Mirror(tmp_path)
    _save(mirror)
    assert json.loads((tmp_path / ".ai26-distributed-offsets.json").read_text()) == {"x.jsonl": 42}
    assert not (tmp_path / ".ai26-distributed-offsets.json.tmp").exists()


def test_a_refused_rename_still_persists_the_offsets(tmp_path: Path, monkeypatch) -> None:
    """The failure mode observed on this host must not leave the offsets stale."""
    mirror = _Mirror(tmp_path)

    def refuse(self, target):  # noqa: ANN001 - matches Path.replace
        raise FileNotFoundError(2, "No such file or directory", str(self))

    monkeypatch.setattr(Path, "replace", refuse)
    _save(mirror)
    assert json.loads((tmp_path / ".ai26-distributed-offsets.json").read_text()) == {"x.jsonl": 42}


def test_offsets_survive_a_restart(tmp_path: Path, monkeypatch) -> None:
    mirror = _Mirror(tmp_path)
    monkeypatch.setattr(Path, "replace", lambda self, target: (_ for _ in ()).throw(OSError))
    _save(mirror)
    reloaded = json.loads((tmp_path / ".ai26-distributed-offsets.json").read_text())
    assert reloaded == {"x.jsonl": 42}
