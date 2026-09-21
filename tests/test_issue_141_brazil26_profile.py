from __future__ import annotations

from pathlib import Path

import pytest

from laclaugpt_data_collection import brazil26_localhost_collect

ROOT = Path(__file__).resolve().parents[1]


def test_brazil26_localhost_wrapper_runs_rss_and_safe_plugin_pass() -> None:
    text = (ROOT / "scripts/run_brazil26_localhost_collect.sh").read_text(encoding="utf-8")

    assert "laclaugpt-server-rss" in text
    assert "laclaugpt_data_collection.brazil26_localhost_collect" in text
    assert text.count("--collection-id brazil26") == 2
    assert "--project-id brazil26" in text
    assert "run_firefox_study.sh" not in text


def test_public_youtube_channel_is_not_guessed_into_video_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "brazil26.toml"
    manifest.write_text(
        """
[[youtube_source]]
name = "official_channel"
homepage = "https://www.youtube.com/@example"
arena = "institutional"
source_family = "official video"
priority = "P2"
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(brazil26_localhost_collect, "build_record_store", lambda _settings: object())
    monkeypatch.setattr(brazil26_localhost_collect, "default_registry", lambda: object())

    result = brazil26_localhost_collect.collect_manifest(manifest)

    assert result["project_id"] == "brazil26"
    assert result["collection_id"] == "brazil26"
    assert result["runs"] == []
    assert result["skipped"] == [
        {
            "source": "official_channel",
            "reason": "no explicit video_urls; channel expansion is never guessed",
        }
    ]


def test_brazil26_non_browser_runner_rejects_cross_study_identity(tmp_path: Path) -> None:
    manifest = tmp_path / "brazil26.toml"
    manifest.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="project_id=collection_id=brazil26"):
        brazil26_localhost_collect.collect_manifest(
            manifest,
            project_id="ai26",
            collection_id="brazil26",
        )


def test_brazil26_public_manifest_keeps_live_targets_private() -> None:
    manifest = (
        ROOT / "configs/studies/brazil26.sources.example.toml"
    ).read_text(encoding="utf-8")
    module = (
        ROOT / "src/laclaugpt_data_collection/brazil26_localhost_collect.py"
    ).read_text(encoding="utf-8")

    assert "[[youtube_source]]" in manifest
    assert "video_urls" not in manifest
    assert "channel expansion is never guessed" in module
    assert '"political_label_ground_truth": False' in module
