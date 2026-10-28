"""Issue #392: cross-host AI26 effective configuration parity."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.ai26_config_fingerprint import FORMAT, compare, fingerprint, main


def test_formatting_does_not_change_effective_fingerprint(tmp_path: Path) -> None:
    a, b, c, d = (tmp_path / p for p in ("a.toml", "b.toml", "a.yaml", "b.yaml"))
    a.write_text('[one]\nx = 1\ny = "two"\n')
    b.write_text('[one]\ny = "two"\nx=1 # comment\n')
    c.write_text('study: ai26\ncollection_policy:\n  publication_date_floor: "2026-09-01"\n')
    d.write_text('collection_policy: {publication_date_floor: "2026-09-01"}\nstudy: ai26\n')
    assert fingerprint(a, c) == fingerprint(b, d)


def test_changes_detected_and_no_values_emitted(tmp_path: Path) -> None:
    sources, study = tmp_path / "sources.toml", tmp_path / "study.yaml"
    sources.write_text('credential = "do-not-output"\n')
    study.write_text('study: ai26\n')
    first = fingerprint(sources, study)
    assert "do-not-output" not in json.dumps(first)
    assert first["format"] == FORMAT
    sources.write_text('credential = "changed"\n')
    second = fingerprint(sources, study)
    assert not compare([first, second])
    assert not compare([first])


def test_compare_reports(tmp_path: Path, capsys) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    report = {"format": FORMAT, "sources_sha256": "a" * 64, "study_sha256": "b" * 64}
    a.write_text(json.dumps(report))
    b.write_text(json.dumps(report))
    assert main(["--compare", str(a), str(b)]) == 0
    assert "AI26_CONFIG_PARITY=match" in capsys.readouterr().out
    b.write_text(json.dumps({**report, "study_sha256": "c" * 64}))
    assert main(["--compare", str(a), str(b)]) == 1
