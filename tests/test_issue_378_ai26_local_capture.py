"""AI26 Firefox capture must run on a host without MongoDB or Allas (#378).

The Brazil26 backend already degraded to a local-only profile; the AI26 backend constructed
``JsonlDistributedMirror`` unconditionally, so on a workstation with no MongoDB URI it died at
startup and the Firefox extension could never be pointed at AI26. These tests pin the split:
a local profile builds no mirror, a distributed profile still does.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from laclaugpt_data_collection import ai26_browser  # noqa: E402


class _Settings:
    def __init__(self, distributed: bool) -> None:
        self.distributed_requested = distributed


def test_local_profile_builds_no_mirror() -> None:
    assert ai26_browser._mirror_if_distributed(
        _Settings(False), "study.yaml", "/tmp/data", 1.0
    ) is None


def test_distributed_profile_still_builds_the_mirror(monkeypatch) -> None:
    built: dict[str, object] = {}

    class FakeMirror:
        def __init__(self, settings, *, study_config, data_root, interval_seconds):
            built.update(study=study_config, root=data_root, interval=interval_seconds)

    monkeypatch.setattr(ai26_browser, "JsonlDistributedMirror", FakeMirror)
    mirror = ai26_browser._mirror_if_distributed(
        _Settings(True), "study.yaml", "/tmp/data", 2.5
    )
    assert isinstance(mirror, FakeMirror)
    assert built == {"study": "study.yaml", "root": "/tmp/data", "interval": 2.5}
