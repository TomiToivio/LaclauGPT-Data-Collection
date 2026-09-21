"""Issue #140: AI26 Laskin Phase 1 non-browser worker invariants."""
import os
from pathlib import Path
import subprocess

from laclaugpt_data_collection.ai26_laskin_runner import load_non_browser_jobs, select_job_window

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "configs" / "studies" / "ai26.sources.example.toml"


def test_laskin_manifest_loader_excludes_browser_only_sources() -> None:
    jobs = load_non_browser_jobs(SOURCES)
    kinds = {job["kind"] for job in jobs}
    assert "x_account" not in kinds
    assert "browser_source" not in kinds
    assert "instagram_account" not in kinds
    assert "tiktok_account" not in kinds
    assert {"web_source", "bluesky_account", "mastodon_account", "youtube_source", "scholarly_query"} <= kinds


def test_laskin_non_browser_window_rotates_without_starving_tail() -> None:
    jobs = [{"kind": "web_source", "name": f"s{i}", "priority": "P1"} for i in range(6)]
    seen = set()
    for step in range(3):
        seen.update(row["name"] for row in select_job_window(jobs, max_jobs=2, rotation=step * 2))
    assert seen == {f"s{i}" for i in range(6)}


def test_laskin_wrapper_hard_disables_browser_and_uses_canonical_ai26_namespace(tmp_path: Path) -> None:
    wrapper = ROOT / "scripts" / "run_ai26_laskin_collect.sh"
    text = wrapper.read_text(encoding="utf-8")
    assert 'LACLAUGPT_BROWSER:-none' in text
    assert '!= "none"' in text
    assert "ai26_laskin_runner" in text
    assert '--collection-id "ai26"' in text

    executable_text = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    ).lower()
    assert "firefox" not in executable_text
    assert "playwright" not in executable_text

    env_file = tmp_path / ".env"
    study_config = tmp_path / "ai26.yaml"
    source_manifest = tmp_path / "ai26.sources.toml"
    env_file.write_text("", encoding="utf-8")
    study_config.write_text("study: ai26\n", encoding="utf-8")
    source_manifest.write_text("", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "LACLAUGPT_ENV_FILE": str(env_file),
            "LACLAUGPT_AI26_STUDY_CONFIG": str(study_config),
            "LACLAUGPT_AI26_SOURCE_MANIFEST": str(source_manifest),
            "LACLAUGPT_AI26_COLLECT_LOCK": str(tmp_path / "collect.lock"),
            "LACLAUGPT_BROWSER": "firefox",
        }
    )
    result = subprocess.run(
        ["bash", str(wrapper)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "refusing Laskin collection" in result.stderr
    assert "browser collection is localhost-only" in result.stderr


def test_laskin_media_worker_uses_shared_remote_pending_media_discovery() -> None:
    runner = (ROOT / "src" / "laclaugpt_data_collection" / "distributed_media_runner.py").read_text(
        encoding="utf-8"
    )
    assert "pending_media_records(" in runner
    assert "remote_records" in runner
    assert "records_by_route" in runner
    assert "MongoDB is authoritative" in runner


def test_laskin_and_localhost_share_project_scoped_backends_not_machine_namespaces() -> None:
    collection = (ROOT / "src" / "laclaugpt_data_collection" / "distributed_capture.py").read_text(
        encoding="utf-8"
    )
    assert 'namespace.mongo_collection("records")' in collection
    assert 'prefix=f"{settings.s3_prefix_root}/{settings.project_id}"' in collection
    assert "settings.machine" in collection
    assert "machine" not in 'namespace.mongo_collection("records")'
