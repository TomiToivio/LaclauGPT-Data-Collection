"""Issue #140: AI26 Laskin Phase 1 non-browser worker invariants."""
from pathlib import Path

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


def test_laskin_wrapper_hard_disables_browser_and_uses_canonical_ai26_namespace() -> None:
    text = (ROOT / "scripts" / "run_ai26_laskin_collect.sh").read_text(encoding="utf-8")
    assert 'LACLAUGPT_BROWSER:-none' in text
    assert '!= "none"' in text
    assert "ai26_laskin_runner" in text
    assert '--collection-id "ai26"' in text
    assert "firefox" not in text.lower()
    assert "playwright" not in text.lower()


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
