"""Capture hygiene and cross-host config fingerprint (#392).

Two follow-ups from the AI26 capture run:
* raw captures were written with a plain append, and two truncated lines were found —
  a crash mid-write used to poison the file for every later reader;
* AC 1 of #378 needs a way to prove two hosts resolve the same study settings, which
  means a comparable hash, not a visual diff of two private YAMLs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from laclaugpt_data_collection import effective_config  # noqa: E402
from laclaugpt_data_collection.store import CollectionStore  # noqa: E402


def _study(tmp_path: Path, *, window_end: str = "2026-12-31", name: str = "a.yaml") -> Path:
    path = tmp_path / name
    path.write_text(
        "study: ai26\n"
        "timezone: UTC\n"
        f"window:\n  start: 2026-09-01\n  end: {window_end}\n"
        "platforms:\n  x:\n    enabled: true\n",
        encoding="utf-8",
    )
    return path


def test_raw_capture_is_written_atomically(tmp_path: Path) -> None:
    store = CollectionStore(tmp_path)
    ref = store.append_raw("x", {"data": {"value": "ok"}})
    path = tmp_path / ref
    assert path.exists()
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert json.loads(path.read_text(encoding="utf-8"))["data"]["value"] == "ok"
    # no half-written staging file may survive a successful write
    assert list(path.parent.glob("*.tmp")) == []
    store.close()


def test_two_writes_produce_two_clean_files(tmp_path: Path) -> None:
    store = CollectionStore(tmp_path)
    refs = [store.append_raw("x", {"n": i}) for i in range(3)]
    assert len(set(refs)) == 3
    for ref in refs:
        assert json.loads((tmp_path / ref).read_text(encoding="utf-8"))
    store.close()


def test_the_same_study_resolves_to_the_same_fingerprint(tmp_path: Path, capsys) -> None:
    study = _study(tmp_path)
    assert effective_config.main(["--project", str(study), "--hash-only"]) == 0
    first = capsys.readouterr().out.strip()
    assert effective_config.main(["--project", str(study), "--hash-only"]) == 0
    second = capsys.readouterr().out.strip()
    assert first == second
    assert first.startswith("sha256:") and len(first) == 71


def test_a_changed_setting_changes_the_fingerprint(tmp_path: Path, capsys) -> None:
    a = _study(tmp_path, name="a.yaml")
    b = _study(tmp_path, window_end="2027-01-31", name="b.yaml")
    effective_config.main(["--project", str(a), "--hash-only"])
    hash_a = capsys.readouterr().out.strip()
    effective_config.main(["--project", str(b), "--hash-only"])
    hash_b = capsys.readouterr().out.strip()
    assert hash_a != hash_b


def test_the_snapshot_never_prints_secret_values(tmp_path: Path, capsys) -> None:
    study = tmp_path / "secret.yaml"
    study.write_text(
        "study: ai26\nwindow:\n  start: 2026-09-01\n  end: 2026-12-31\n"
        "access_token: super-secret-value\n",
        encoding="utf-8",
    )
    assert effective_config.main(["--project", str(study)]) == 0
    printed = capsys.readouterr().out
    assert "super-secret-value" not in printed
    assert json.loads(printed)["effective_config_hash"]
