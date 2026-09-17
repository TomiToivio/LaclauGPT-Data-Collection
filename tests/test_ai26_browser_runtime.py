from __future__ import annotations

import json
from pathlib import Path

import pytest

from laclaugpt_data_collection import ai26_browser, distributed_media_runner

ROOT = Path(__file__).resolve().parents[1]


def _write_study(path: Path, study: str) -> Path:
    path.write_text(
        "\n".join(
            [
                f"study: {study}",
                "timezone: UTC",
                "window:",
                "  start: '2026-09-01'",
                "  end: '2026-12-31'",
                "platforms:",
                "  x:",
                "    enabled: true",
                "    base_urls: ['https://x.com/{handle}']",
                "groups:",
                "  - id: synthetic",
                "    name: Synthetic",
                "    arena: test",
                "    accounts:",
                "      x: [example_account]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_ai26_identity_accepts_ai26_and_rejects_other_study(tmp_path: Path) -> None:
    ai26 = _write_study(tmp_path / "ai26.yaml", "ai26")
    other = _write_study(tmp_path / "other.yaml", "brazil26")

    assert ai26_browser._ensure_ai26_study(ai26) == "ai26"
    with pytest.raises(ValueError, match="non-AI26"):
        ai26_browser._ensure_ai26_study(other)


def test_ai26_study_config_uses_historical_environment_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI26_CONFIG", "/private/ai26.yaml")
    assert ai26_browser._study_config(None) == "/private/ai26.yaml"


def test_ai26_backend_refuses_non_loopback_before_network_calls(tmp_path: Path) -> None:
    config = _write_study(tmp_path / "ai26.yaml", "ai26")
    with pytest.raises(ValueError, match="localhost/loopback"):
        ai26_browser.run_backend(
            study_config=str(config),
            data_root=str(tmp_path / "data"),
            host="192.0.2.10",
            port=8766,
            sync_interval=1.0,
        )


def test_ai26_mirror_rejects_cross_study_collection_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_study(tmp_path / "ai26.yaml", "ai26")
    normalized = tmp_path / "data" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "x.jsonl").write_text(
        json.dumps({"collection_id": "brazil26", "source_url": "https://example.test/1"})
        + "\n",
        encoding="utf-8",
    )

    class FakeSink:
        def __init__(self, settings: object) -> None:
            del settings

        def assert_private_config(self, path: str | Path) -> None:
            del path

        def ingest(self, record: dict[str, object]) -> None:
            raise AssertionError(f"cross-study row must not be ingested: {record}")

    monkeypatch.setattr(ai26_browser, "DistributedCaptureSink", FakeSink)
    mirror = ai26_browser.JsonlDistributedMirror(
        object(),  # type: ignore[arg-type]
        study_config=config,
        data_root=tmp_path / "data",
    )
    with pytest.raises(ValueError, match="refuses collection_id"):
        mirror.scan_once()


def test_media_lock_prevents_overlapping_cron_runs(tmp_path: Path) -> None:
    with distributed_media_runner.media_run_lock(tmp_path) as lock_path:
        assert lock_path.exists()
        with pytest.raises(distributed_media_runner.MediaRunLockedError, match="already active"):
            with distributed_media_runner.media_run_lock(tmp_path):
                pass
    assert not (tmp_path / ".distributed-media.lock").exists()


def test_ai26_public_env_template_has_placeholders_only() -> None:
    text = (ROOT / "configs" / "ai26.browser.env.example").read_text(encoding="utf-8")
    assert "LACLAUGPT_PROJECT_ID=ai26" in text
    assert "127.0.0.1" in text
    assert "mongodb://HOST:PORT/" in text
    assert "LaclauGPT-Private/collection/ai26" in text
