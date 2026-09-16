from pathlib import Path

import yaml

from laclaugpt_data_collection.effective_config import (
    resolve_collection_config,
    stamp_config_provenance,
)
from laclaugpt_data_collection.models import CanonicalRecord


def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_project_arena_machine_execution_resolution(tmp_path: Path) -> None:
    project = _write_yaml(
        tmp_path / "project.yaml",
        {
            "project": "ai26",
            "dataset": {"title": "AI26", "languages": ["en", "fi"]},
            "analysis": {"laclau": True},
            "window": {"start": "2026-09-01", "end": "2026-12-31"},
            "collector_defaults": {"retry": {"max_attempts": 3}},
        },
    )
    arena = _write_yaml(
        tmp_path / "elites.yaml",
        {
            "arena": "elites",
            "project": "ai26",
            "dataset": {
                "title": "AI elites",
                "platforms": ["web", "rss"],
                "languages": ["en"],
                "countries": ["US", "EU"],
                "analytic_hints": {
                    "signifiers": ["abundance", "existential risk"],
                    "formations": ["accelerationism", "doomerism", "ai critical"],
                },
            },
            "model": {"text": "ignored-analysis-model"},
        },
    )
    machine = tmp_path / "laptop.toml"
    machine.write_text(
        'machine = "laptop"\n[storage]\nrecords = "sqlite"\nobjects = "filesystem"\n',
        encoding="utf-8",
    )

    effective = resolve_collection_config(
        project=project,
        arena=arena,
        machine=machine,
        execution={"execution": "cli", "browser": "firefox-local"},
    )

    assert effective.data["study"] == "ai26"
    assert effective.data["arena"] == "elites"
    assert effective.data["machine"] == "laptop"
    assert effective.data["execution"] == "cli"
    assert effective.data["storage"]["records"] == "sqlite"
    assert effective.data["arena_config"]["platforms"] == ["web", "rss"]
    assert effective.data["arena_config"]["discovery_hints"]["formations"] == [
        "accelerationism",
        "doomerism",
        "ai critical",
    ]
    assert "analysis" not in effective.data
    assert "model" not in effective.data


def test_private_override_and_safe_snapshot_redact_targets_and_secrets(tmp_path: Path) -> None:
    project = _write_yaml(
        tmp_path / "project.yaml",
        {
            "study": "ai26",
            "window": {"start": "2026-09-01", "end": "2026-12-31"},
            "collector_defaults": {"retry": {"max_attempts": 3}},
        },
    )
    private = _write_yaml(
        tmp_path / "private-study.yaml",
        {
            "groups": [
                {"id": "real-list", "accounts": {"x": ["private_research_target"]}}
            ],
            "collector_defaults": {
                "retry": {"max_attempts": 5},
                "checkpoint": {"enabled": True, "resume": True},
            },
            "api_token": "synthetic-not-a-real-secret",
        },
    )

    effective = resolve_collection_config(project=project, private_overrides=[private])
    assert effective.data["collector_defaults"]["retry"]["max_attempts"] == 5
    assert effective.data["collector_defaults"]["checkpoint"]["resume"] is True

    snapshot = effective.safe_snapshot()
    rendered = str(snapshot)
    assert "private_research_target" not in rendered
    assert "synthetic-not-a-real-secret" not in rendered
    assert str(tmp_path) not in rendered
    assert snapshot["config"]["api_token"] == "<redacted>"
    assert snapshot["layers"][-1]["source_id"] == "private-study.yaml"


def test_effective_hash_is_deterministic_and_changes_with_override() -> None:
    project = {
        "study": "ai26",
        "window": {"start": "2026-09-01", "end": "2026-12-31"},
        "collector_defaults": {"pagination": {"max_pages_per_poll": 3}},
    }
    first = resolve_collection_config(project=project)
    second = resolve_collection_config(project=project)
    changed = resolve_collection_config(
        project=project,
        overrides={"collector_defaults": {"pagination": {"max_pages_per_poll": 2}}},
    )
    assert first.digest == second.digest
    assert first.digest != changed.digest


def test_config_provenance_is_attached_without_private_config_payload() -> None:
    effective = resolve_collection_config(
        project={"study": "ai26", "window": {"start": "2026-09-01", "end": "2026-12-31"}},
        arena={"arena": "elites"},
        machine={"machine": "linux-server", "storage": {"records": "mongodb"}},
        execution={"execution": "cron"},
        private_overrides=[{"accounts": ["private-target"], "password": "private-value"}],
    )
    record = CanonicalRecord(source_url="https://example.org/post/1")
    stamp_config_provenance(record, effective)
    metadata = record.provenance[-1].metadata["collection_config"]

    assert metadata["study"] == "ai26"
    assert metadata["arena"] == "elites"
    assert metadata["machine"] == "linux-server"
    assert metadata["execution"] == "cron"
    assert metadata["effective_config_hash"] == effective.digest
    assert "private-target" not in str(metadata)
    assert "private-value" not in str(metadata)


def test_project_only_config_works_without_private_repo() -> None:
    effective = resolve_collection_config(
        project={
            "study": "synthetic-study",
            "window": {"start": "2026-01-01", "end": "2026-12-31"},
            "platforms": {"rss": {"enabled": True}},
        }
    )
    assert effective.data["study"] == "synthetic-study"
    assert [layer.kind for layer in effective.layers] == ["project"]


def test_invalid_window_fails_visibly() -> None:
    try:
        resolve_collection_config(
            project={
                "study": "broken",
                "window": {"start": "2026-12-31", "end": "2026-01-01"},
            }
        )
    except ValueError as exc:
        assert "window start" in str(exc)
    else:
        raise AssertionError("invalid collection window should fail")
