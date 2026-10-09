"""Issue #233 acceptance coverage: Brazil26 localhost, X/IG/TikTok-only, Allas.

These tests are offline by design: they assert the *policy* and the *wiring* the
deployment depends on, not live platform downloads. CI cannot authenticate to X,
Instagram, TikTok, MongoDB or CSC Allas, so "a video downloaded from TikTok"
is out of scope here; what is in scope is that the code refuses every other
source family, that the distributed media path is reachable and idempotent, and
that the cron cadence is 30 minutes with no stale 15-minute entry.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from laclaugpt_data_collection import source_allowlist as sa

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Source allowlist: X / Instagram / TikTok only
# --------------------------------------------------------------------------- #

def test_brazil26_platforms_are_exactly_the_three() -> None:
    assert sa.BRAZIL26_PLATFORMS == ("x", "instagram", "tiktok")


def test_browser_platforms_map_to_no_plugin() -> None:
    """X/IG/TikTok are Firefox capture, so they must enable no non-browser plugin."""
    assert sa.enabled_plugin_ids({"enabled_platforms": ["x", "instagram", "tiktok"]}) == frozenset()


def test_enabling_rss_resolves_to_the_rss_plugin() -> None:
    assert sa.enabled_plugin_ids({"enabled_platforms": ["rss"]}) == frozenset({"rss"})


def test_a_manifest_with_no_declaration_enables_nothing() -> None:
    """No implicit default: an old manifest must not silently re-enable RSS."""
    assert sa.enabled_platforms({}) == frozenset()
    assert sa.enabled_plugin_ids({}) == frozenset()


def test_unknown_platform_is_an_error_not_a_silent_pass() -> None:
    with pytest.raises(sa.SourceAllowlistError, match="unknown source platform"):
        sa.enabled_platforms({"enabled_platforms": ["myspace"]})


def test_assert_brazil26_only_accepts_the_three() -> None:
    assert sa.assert_brazil26_only({"enabled_platforms": ["x", "instagram", "tiktok"]}) == frozenset(
        {"x", "instagram", "tiktok"}
    )


@pytest.mark.parametrize("extra", ["rss", "youtube", "telegram", "reddit", "bluesky", "mastodon", "arxiv"])
def test_assert_brazil26_only_rejects_every_other_family(extra: str) -> None:
    with pytest.raises(sa.SourceAllowlistError, match="X/Instagram/TikTok only"):
        sa.assert_brazil26_only({"enabled_platforms": ["x", extra]})


def test_the_public_example_manifest_is_brazil26_policy_compliant() -> None:
    """The shipped example must itself pass the policy the deployment enforces."""
    manifest = sa.load_manifest(ROOT / "configs/studies/brazil26.sources.example.toml")
    assert sa.assert_brazil26_only(manifest) == frozenset({"x", "instagram", "tiktok"})
    # The documented institutional rows must be disabled, never collected.
    assert all(not row.get("enabled", True) for row in manifest.get("feed", []))


def test_allowlist_cli_passes_and_fails() -> None:
    import sys

    manifest = ROOT / "configs/studies/brazil26.sources.example.toml"
    ok = subprocess.run(
        [sys.executable, "-m",
         "laclaugpt_data_collection.source_allowlist",
         "--manifest", str(manifest), "--require-brazil26-only"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert ok.returncode == 0, ok.stderr

    # RSS is not enabled, so requiring it must fail with a non-zero code.
    rss = subprocess.run(
        [sys.executable, "-m",
         "laclaugpt_data_collection.source_allowlist",
         "--manifest", str(manifest), "--require-plugin", "rss"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert rss.returncode == 3
    assert "not enabled" in rss.stderr


# --------------------------------------------------------------------------- #
# Distributed media wrapper enables Allas + Mongo (the C1 fix)
# --------------------------------------------------------------------------- #

def test_distributed_media_wrapper_pins_s3_and_mongodb() -> None:
    text = (ROOT / "scripts/run_brazil26_localhost_media_distributed.sh").read_text(encoding="utf-8")
    assert 'LACLAUGPT_OBJECT_BACKEND=${LACLAUGPT_OBJECT_BACKEND:-s3}' in text
    assert 'LACLAUGPT_RECORD_BACKEND=${LACLAUGPT_RECORD_BACKEND:-mongodb}' in text
    # It must NOT clear the remote selectors the way the local-first wrapper does.
    assert "LACLAUGPT_S3_BUCKET=\n" not in text
    assert "LACLAUGPT_MONGODB_URI=\n" not in text
    # Fail closed rather than falling back to filesystem.
    assert "refusing to fall back to filesystem" in text
    assert "laclaugpt-distributed-media" in text


def test_local_first_wrapper_keeps_its_zero_infrastructure_guarantee() -> None:
    """The new wrapper must not have changed the existing local-first behaviour."""
    text = (ROOT / "scripts/run_brazil26_localhost_media.sh").read_text(encoding="utf-8")
    assert "LACLAUGPT_OBJECT_BACKEND=filesystem" in text
    assert "explicit remote mirroring belongs to run_brazil26_localhost_sync.sh".lower() in text.lower()


# --------------------------------------------------------------------------- #
# Media platform allowlist (the media worker honours the policy)
# --------------------------------------------------------------------------- #

def test_media_downloader_refuses_a_disabled_platform(tmp_path: Path, monkeypatch) -> None:
    from laclaugpt_data_collection.media import MediaDownloader
    from laclaugpt_data_collection.store import CollectionStore

    store = CollectionStore(tmp_path)
    try:
        downloader = MediaDownloader(store, allowed_platforms=frozenset({"x", "instagram", "tiktok"}))

        def rec(platform: str) -> dict:
            return {
                "collection_id": "brazil26",
                "source_url": f"https://{platform}.example.invalid/1",
                "source": {"platform": platform},
                "content": {"media_references": [
                    {"media_index": 0, "kind": "video", "url": f"https://cdn.example.invalid/{platform}.mp4"}
                ]},
            }

        jobs = downloader.enqueue_from_records([rec("x"), rec("tiktok"), rec("youtube"), rec("rss")])
        platforms = sorted(job.platform for job in jobs)
        assert platforms == ["tiktok", "x"], platforms
    finally:
        store.close()


def test_media_downloader_without_allowlist_accepts_everything(tmp_path: Path) -> None:
    from laclaugpt_data_collection.media import MediaDownloader
    from laclaugpt_data_collection.store import CollectionStore

    store = CollectionStore(tmp_path)
    try:
        downloader = MediaDownloader(store, allowed_platforms=None)
        record = {
            "collection_id": "brazil26",
            "source_url": "https://youtube.example.invalid/1",
            "source": {"platform": "youtube"},
            "content": {"media_references": [
                {"media_index": 0, "kind": "video", "url": "https://cdn.example.invalid/y.mp4"}
            ]},
        }
        assert len(downloader.enqueue_from_records([record])) == 1
    finally:
        store.close()


def test_media_runner_reads_the_allowlist_from_the_manifest(tmp_path: Path, monkeypatch) -> None:
    from laclaugpt_data_collection import distributed_media_runner as dmr

    manifest = tmp_path / "brazil26.sources.toml"
    manifest.write_text('enabled_platforms = ["x", "instagram", "tiktok"]\n', encoding="utf-8")
    monkeypatch.setenv("LACLAUGPT_SOURCE_MANIFEST", str(manifest))
    study = tmp_path / "study.yaml"
    study.write_text("study: brazil26\n", encoding="utf-8")

    allowed = dmr._allowed_platforms(study, tmp_path)
    assert allowed == frozenset({"x", "instagram", "tiktok"})


def test_media_runner_rejects_a_policy_violating_manifest(tmp_path: Path, monkeypatch) -> None:
    from laclaugpt_data_collection import distributed_media_runner as dmr
    from laclaugpt_data_collection.source_allowlist import SourceAllowlistError

    manifest = tmp_path / "brazil26.sources.toml"
    manifest.write_text('enabled_platforms = ["x", "rss"]\n', encoding="utf-8")
    monkeypatch.setenv("LACLAUGPT_SOURCE_MANIFEST", str(manifest))
    study = tmp_path / "study.yaml"
    study.write_text("study: brazil26\n", encoding="utf-8")

    with pytest.raises(SourceAllowlistError):
        dmr._allowed_platforms(study, tmp_path)


# --------------------------------------------------------------------------- #
# Cron: 30-minute cadence, no retained 15-minute entry
# --------------------------------------------------------------------------- #

def test_installer_uses_a_thirty_minute_media_cadence() -> None:
    """The cadence is the fact; the wrapper NAME is now selectable (#233 AC3).

    The line is emitted through `$MEDIA_WRAPPER`, so asserting the literal wrapper
    name would pin an implementation detail that must vary between local-first and
    Allas modes. Assert the cadence and that exactly one media entry is emitted.
    """
    text = (ROOT / "scripts/install_cron_brazil26.sh").read_text(encoding="utf-8")
    assert "*/30 * * * *" in text
    # exactly one media cron line, and it must be the 30-minute one
    media_lines = [
        line for line in text.splitlines()
        if "scripts/$MEDIA_WRAPPER" in line or "run_brazil26_localhost_media" in line
        if line.strip().startswith(("*/30", "*/15", "*"))
    ]
    assert media_lines, "the media cron entry is missing"
    assert all("*/30" in line for line in media_lines), media_lines
    assert not any("*/15" in line for line in media_lines), "a 15-minute entry survives"


def test_installer_can_schedule_the_allas_media_worker() -> None:
    """#233 AC3 needs a *scheduled* Allas upload, so the mode must be selectable.

    Without this the distributed wrapper exists but can never be installed, and the
    acceptance criterion cannot be met on any host.
    """
    text = (ROOT / "scripts/install_cron_brazil26.sh").read_text(encoding="utf-8")
    assert "LACLAUGPT_BRAZIL26_MEDIA_MODE" in text
    assert "run_brazil26_localhost_media_distributed.sh" in text
    # local-first stays the default
    assert "LACLAUGPT_BRAZIL26_MEDIA_MODE:-local" in text
    # and a bad mode fails closed rather than silently installing the wrong worker
    assert "must be 'local' or 'allas'" in text


def test_switching_mode_removes_the_other_wrappers_entry() -> None:
    """Two media entries would fight for the same lock, so the other mode is stripped."""
    text = (ROOT / "scripts/install_cron_brazil26.sh").read_text(encoding="utf-8")
    assert "OTHER_WRAPPER" in text
    assert "other mode" in text


def test_installer_strips_a_stale_fifteen_minute_entry() -> None:
    text = (ROOT / "scripts/install_cron_brazil26.sh").read_text(encoding="utf-8")
    # both wrappers must be matched, so switching mode cannot leave a 15-minute entry
    assert "run_brazil26_localhost_media(_distributed)?\\.sh" in text
    assert "stale 15-minute" in text


def test_installer_is_idempotent_against_a_synthetic_crontab(tmp_path: Path) -> None:
    """Running the installer twice must not duplicate the managed block."""
    env = tmp_path / "brazil26-localhost.env"
    env.write_text("LACLAUGPT_PROJECT_ID=brazil26\n", encoding="utf-8")
    study = tmp_path / "study.yaml"
    study.write_text("study: brazil26\n", encoding="utf-8")
    crontab_store = tmp_path / "crontab.txt"
    crontab_store.write_text("", encoding="utf-8")

    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "crontab").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"STORE={crontab_store}\n"
        'if [[ "$1" == "-l" ]]; then cat "$STORE" 2>/dev/null || true; exit 0; fi\n'
        'cp "$1" "$STORE"\n',
        encoding="utf-8",
    )
    (shim / "crontab").chmod(0o755)

    def run() -> str:
        proc = subprocess.run(
            ["bash", str(ROOT / "scripts/install_cron_brazil26.sh")],
            capture_output=True, text=True,
            env={
                "PATH": f"{shim}:/usr/bin:/bin",
                "LACLAUGPT_ENV_FILE": str(env),
                "LACLAUGPT_STUDY_CONFIG": str(study),
                "LACLAUGPT_DATA_ROOT": str(tmp_path / "data"),
                "HOME": str(tmp_path),
            },
            cwd=ROOT,
        )
        assert proc.returncode == 0, proc.stderr
        return crontab_store.read_text(encoding="utf-8")

    first = run()
    second = run()
    assert first.count("# BEGIN LACLAUGPT BRAZIL26") == 1
    assert second.count("# BEGIN LACLAUGPT BRAZIL26") == 1
    assert second.count("run_brazil26_localhost_media.sh") == 1
    assert "*/15" not in second
