"""#440: a store outage must be declared, not swallowed by a traceback.

When MongoDB went unreachable on 2026-11-16, each hourly tick wrote a
ServerSelectionTimeoutError traceback to the cron log and nothing that stated how
many observation windows were lost. The issue allows two shapes -- a durable local
spool, or a declaration -- and asks that either way the artifact answers "how many
windows were missed and are they recoverable".

These tests pin the declaration: the tick exits non-zero and prints one structured
record naming the loss, and it does so only for store-unavailability errors.
"""

from __future__ import annotations

import json

import pytest

from laclaugpt_data_collection import ai26_laskin_runner as runner


def _argv(tmp_path):
    study = tmp_path / "ai26.yaml"
    manifest = tmp_path / "ai26.sources.toml"
    study.write_text("study: ai26\n", encoding="utf-8")
    manifest.write_text("", encoding="utf-8")
    return ["--study-config", str(study), "--source-manifest", str(manifest)]


def test_store_outage_prints_a_declaration_and_exits_three(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "Settings", lambda: type("S", (), {
        "project_id": "ai26", "mongodb_uri": "", "mongodb_database": "x",
        "mongodb_connect_timeout_ms": 1000,
    })())

    def boom(*_a, **_kw):
        raise runner.STORE_UNAVAILABLE_ERRORS[0]("86.50.228.141:27017 timed out")

    monkeypatch.setattr(runner, "run_phase1_laskin", boom)

    code = runner.main(_argv(tmp_path))
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert code == 3, "a lost window must not look like a clean tick"
    assert out["status"] == "store_unavailable"
    assert out["windows_missed"] == 1
    assert out["missed_windows_recoverable"] is False
    assert "the canonical record store was unreachable" in out["declaration"]
    assert out["errors"], "the underlying error is still reported"


def test_a_non_store_error_is_not_declared_as_a_lost_window(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "Settings", lambda: type("S", (), {
        "project_id": "ai26", "mongodb_uri": "", "mongodb_database": "x",
        "mongodb_connect_timeout_ms": 1000,
    })())

    def boom(*_a, **_kw):
        raise ValueError("a real bug, not an outage")

    monkeypatch.setattr(runner, "run_phase1_laskin", boom)

    with pytest.raises(ValueError):
        runner.main(_argv(tmp_path))
