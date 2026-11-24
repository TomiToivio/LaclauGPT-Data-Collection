"""Issue #470: audit X bridge targets without silently assigning research arenas."""

import json
from pathlib import Path

import pytest

from laclaugpt_data_collection.manifest_drift import (
    compare_bridge_targets,
    compare_manifests,
    drift_summary,
)


def _manifest(tmp_path: Path, name: str, handles: tuple[str, ...]) -> Path:
    path = tmp_path / name
    path.write_text(
        "".join(f'[[x_account]]\nhandle = "{handle}"\n' for handle in handles),
        encoding="utf-8",
    )
    return path


def _targets(tmp_path: Path, handles: object) -> Path:
    path = tmp_path / "bridge.json"
    path.write_text(json.dumps(handles), encoding="utf-8")
    return path


def test_bridge_only_drift_is_not_an_all_clear(tmp_path: Path) -> None:
    deployed = _manifest(tmp_path, "deployed.toml", ("MIRIBerkeley",))
    tracked = _manifest(tmp_path, "tracked.toml", ("MIRIBerkeley",))
    bridge = _targets(tmp_path, ["@MIRIBerkeley", "CAIS"])
    original = compare_manifests(deployed, tracked)
    assert original["in_sync"] is True
    report = compare_bridge_targets(deployed, tracked, bridge)
    assert report["checked"] is True
    assert report["undeclared_bridge_handles"] == ["cais"]
    assert report["undeployed_bridge_handles"] == ["cais"]
    assert report["sampling_decision_required"] is True
    original["x_bridge"] = report
    original["in_sync"] = original["in_sync"] and report["in_sync"]
    assert "cais" in drift_summary(original)


def test_declared_targets_are_compared_case_insensitively(tmp_path: Path) -> None:
    deployed = _manifest(tmp_path, "deployed.toml", ("MIRIBerkeley",))
    tracked = _manifest(tmp_path, "tracked.toml", ("MIRIBerkeley",))
    report = compare_bridge_targets(deployed, tracked, _targets(tmp_path, ["@miriberkeley"]))
    assert report["in_sync"] is True
    assert report["bridge_target_count"] == 1


def test_bridge_missing_from_deployment_is_visible(tmp_path: Path) -> None:
    deployed = _manifest(tmp_path, "deployed.toml", ())
    tracked = _manifest(tmp_path, "tracked.toml", ("CAIS",))
    report = compare_bridge_targets(deployed, tracked, _targets(tmp_path, ["CAIS"]))
    assert report["undeclared_bridge_handles"] == []
    assert report["undeployed_bridge_handles"] == ["cais"]
    assert report["in_sync"] is False


@pytest.mark.parametrize("payload", [{"handles": ["CAIS"]}, ["CAIS", 3], ["CAIS", "@cais"], ["https://x.com/CAIS"]])
def test_invalid_bridge_target_lists_fail_closed(tmp_path: Path, payload: object) -> None:
    manifest = _manifest(tmp_path, "manifest.toml", ())
    with pytest.raises(ValueError):
        compare_bridge_targets(manifest, manifest, _targets(tmp_path, payload))


def test_missing_bridge_file_is_not_treated_as_checked(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, "manifest.toml", ())
    with pytest.raises(FileNotFoundError):
        compare_bridge_targets(manifest, manifest, tmp_path / "missing.json")
