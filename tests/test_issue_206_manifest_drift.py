# -*- coding: utf-8 -*-
"""Issue #206 — the running pipeline must be able to see that it is behind the plan.

The deployed manifest under `data/` is gitignored runtime config. The audited
plan lives in `configs/studies/`. When the plan gains a source, nothing reports
that the running set is behind it: measured 2026-10-02, deployed 19 feeds vs
tracked 23, so audited-and-committed sources produced no records at all.

`manifest_drift` makes that difference exact and observable. These tests pin the
comparison semantics, because a drift report that is subtly wrong is worse than
none — it would clear a real gap or raise a false one.

All fixtures are synthetic; no real manifest is read.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from laclaugpt_data_collection.manifest_drift import (
    compare_manifests,
    drift_summary,
    load_manifest_rows,
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _feed(url: str, **extra: str) -> str:
    fields = "".join(f'{k} = "{v}"\n' for k, v in extra.items())
    return f'[[feed]]\nname = "{url}"\nfeed_url = "{url}"\n{fields}\n'


class TestComparisonSemantics:
    def test_identical_manifests_are_in_sync(self, tmp_path: Path) -> None:
        body = _feed("https://a.example/feed") + _feed("https://b.example/feed")
        a = _write(tmp_path, "a.toml", body)
        b = _write(tmp_path, "b.toml", body)
        report = compare_manifests(a, b)
        assert report["in_sync"] is True
        assert report["added"] == [] and report["removed"] == []
        assert report["drift_kinds"] == []

    def test_a_source_in_the_plan_but_not_deployed_is_ADDED(self, tmp_path: Path) -> None:
        """The #206 direction: audited sources never reach the running pipeline."""
        deployed = _write(tmp_path, "d.toml", _feed("https://a.example/feed"))
        tracked = _write(
            tmp_path, "t.toml",
            _feed("https://a.example/feed") + _feed("https://new.example/feed"),
        )
        report = compare_manifests(deployed, tracked)
        assert report["in_sync"] is False
        assert report["drift_kinds"] == ["feed"]
        assert report["counts"]["feed"] == {
            "deployed": 1, "tracked": 2, "added": 1, "removed": 0, "drift": 1,
        }
        assert report["added"] == ["feed:feed_url=https://new.example/feed"]

    def test_a_source_deployed_but_no_longer_audited_is_REMOVED(self, tmp_path: Path) -> None:
        """The hand-edit direction: the running set still polls something withdrawn."""
        deployed = _write(
            tmp_path, "d.toml",
            _feed("https://a.example/feed") + _feed("https://stale.example/feed"),
        )
        tracked = _write(tmp_path, "t.toml", _feed("https://a.example/feed"))
        report = compare_manifests(deployed, tracked)
        assert report["removed"] == ["feed:feed_url=https://stale.example/feed"]
        assert report["added"] == []

    def test_a_trailing_slash_is_not_a_source_change(self, tmp_path: Path) -> None:
        """The #205 redirect class must not read as drift."""
        deployed = _write(tmp_path, "d.toml", _feed("https://a.example/feed"))
        tracked = _write(tmp_path, "t.toml", _feed("https://a.example/feed/"))
        assert compare_manifests(deployed, tracked)["in_sync"] is True

    def test_a_disabled_row_is_not_counted_on_either_side(self, tmp_path: Path) -> None:
        """Drift must not be reported for a row the loader would skip."""
        deployed = _write(tmp_path, "d.toml", _feed("https://a.example/feed"))
        tracked = _write(
            tmp_path, "t.toml",
            _feed("https://a.example/feed")
            + '[[feed]]\nname = "off"\nfeed_url = "https://off.example/feed"\nenabled = false\n',
        )
        report = compare_manifests(deployed, tracked)
        assert report["in_sync"] is True, "a disabled tracked row is not a gap"

    def test_the_same_url_in_two_kinds_does_not_collide(self, tmp_path: Path) -> None:
        """A feed and a web_source can share a URL and route differently."""
        tracked = _write(
            tmp_path, "t.toml",
            _feed("https://a.example/x")
            + '[[web_source]]\nname = "web_a"\nurl = "https://a.example/x"\narena = "elites"\n',
        )
        deployed = _write(tmp_path, "d.toml", _feed("https://a.example/x"))
        report = compare_manifests(deployed, tracked)
        assert report["counts"]["web_source"]["added"] == 1
        assert report["added"] == ["web_source:url=https://a.example/x"]

    def test_kinds_are_reported_independently(self, tmp_path: Path) -> None:
        deployed = _write(
            tmp_path, "d.toml",
            _feed("https://a.example/feed")
            + '[[bluesky_account]]\nname = "b1"\nhandle = "one.bsky.social"\n',
        )
        tracked = _write(
            tmp_path, "t.toml",
            _feed("https://a.example/feed")
            + _feed("https://b.example/feed")
            + '[[bluesky_account]]\nname = "b1"\nhandle = "one.bsky.social"\n'
            + '[[bluesky_account]]\nname = "b2"\nhandle = "two.bsky.social"\n',
        )
        report = compare_manifests(deployed, tracked)
        assert report["counts"]["feed"]["added"] == 1
        assert report["counts"]["bluesky_account"]["added"] == 1
        assert set(report["drift_kinds"]) == {"feed", "bluesky_account"}

    def test_totals_are_reported(self, tmp_path: Path) -> None:
        deployed = _write(tmp_path, "d.toml", _feed("https://a.example/feed"))
        tracked = _write(
            tmp_path, "t.toml",
            _feed("https://a.example/feed") + _feed("https://b.example/feed"),
        )
        report = compare_manifests(deployed, tracked)
        assert report["deployed_total"] == 1
        assert report["tracked_total"] == 2


class TestSummary:
    def test_in_sync_summary_says_so(self) -> None:
        body = _feed("https://a.example/feed")
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.toml"
            p.write_text(body, encoding="utf-8")
            report = compare_manifests(p, p)
        assert "in sync" in drift_summary(report)

    def test_drift_summary_names_the_counts_and_both_directions(self, tmp_path: Path) -> None:
        deployed = _write(tmp_path, "d.toml", _feed("https://a.example/feed"))
        tracked = _write(
            tmp_path, "t.toml",
            _feed("https://a.example/feed") + _feed("https://b.example/feed"),
        )
        summary = drift_summary(compare_manifests(deployed, tracked))
        assert "DRIFT" in summary
        assert "1 audited source(s) not deployed" in summary
        assert "0 deployed source(s) no longer audited" in summary


class TestLoaderContract:
    def test_a_missing_manifest_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_manifest_rows(tmp_path / "nope.toml")

    def test_a_non_array_table_raises(self, tmp_path: Path) -> None:
        bad = _write(tmp_path, "bad.toml", 'feed = "not-an-array"\n')
        with pytest.raises(ValueError, match="must be an array of tables"):
            load_manifest_rows(bad)

    def test_the_cli_exposes_the_command(self) -> None:
        """The report is only useful if it is reachable from the standard CLI."""
        from laclaugpt_data_collection.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            ["manifest-drift", "--deployed", "d.toml", "--tracked", "t.toml", "--fail-on-drift"]
        )
        assert args.func.__name__ == "_manifest_drift"
        assert args.fail_on_drift is True


class TestCycleIntegration:
    """The drift report is only useful if the running cycle emits it (#206)."""

    def test_the_runner_accepts_a_tracked_plan_and_reports_drift(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from laclaugpt_data_collection import ai26_laskin_runner as runner
        from laclaugpt_data_collection.config import Settings

        deployed = _write(tmp_path, "deployed.toml", _feed("https://a.example/feed"))
        tracked = _write(
            tmp_path, "tracked.toml",
            _feed("https://a.example/feed") + _feed("https://b.example/feed"),
        )

        class Sink:
            notification_errors: list = []

            def __init__(self, settings):  # noqa: ANN001
                pass

            def assert_private_config(self, path):  # noqa: ANN001
                pass

            def ingest_with_status(self, payload):  # noqa: ANN001
                return payload, True

        monkeypatch.setattr(runner, "DistributedCaptureSink", Sink)
        monkeypatch.setattr(runner, "load_non_browser_jobs", lambda path: [])
        monkeypatch.setattr(runner, "preflight_optional_dependencies", lambda jobs: [])
        monkeypatch.setattr(runner, "run_phase1_rss", lambda *a, **kw: {"records_synced": 0})

        result = runner.run_phase1_laskin(
            Settings(_env_file=None, project_id="ai26"),
            study_config=tmp_path / "ai26.yaml",
            source_manifest=deployed,
            tracked_plan=tracked,
            rotation=0,
        )
        drift = result["manifest_drift"]
        assert drift is not None, "a cycle with a tracked plan must report drift"
        assert drift["in_sync"] is False
        assert drift["added"] == ["feed:feed_url=https://b.example/feed"]
        assert "DRIFT" in drift["summary"]

    def test_without_a_tracked_plan_the_field_is_present_and_null(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The field shape must be stable for log parsers even when not requested."""
        from laclaugpt_data_collection import ai26_laskin_runner as runner
        from laclaugpt_data_collection.config import Settings

        deployed = _write(tmp_path, "deployed.toml", _feed("https://a.example/feed"))

        class Sink:
            notification_errors: list = []

            def __init__(self, settings):  # noqa: ANN001
                pass

            def assert_private_config(self, path):  # noqa: ANN001
                pass

            def ingest_with_status(self, payload):  # noqa: ANN001
                return payload, True

        monkeypatch.setattr(runner, "DistributedCaptureSink", Sink)
        monkeypatch.setattr(runner, "load_non_browser_jobs", lambda path: [])
        monkeypatch.setattr(runner, "preflight_optional_dependencies", lambda jobs: [])
        monkeypatch.setattr(runner, "run_phase1_rss", lambda *a, **kw: {"records_synced": 0})

        result = runner.run_phase1_laskin(
            Settings(_env_file=None, project_id="ai26"),
            study_config=tmp_path / "ai26.yaml",
            source_manifest=deployed,
            rotation=0,
        )
        assert "manifest_drift" in result
        assert result["manifest_drift"] is None

    def test_a_broken_tracked_plan_does_not_fail_the_cycle(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A reporting aid must never take the collection down."""
        from laclaugpt_data_collection import ai26_laskin_runner as runner
        from laclaugpt_data_collection.config import Settings

        deployed = _write(tmp_path, "deployed.toml", _feed("https://a.example/feed"))
        broken = _write(tmp_path, "broken.toml", "feed = 7\n")

        class Sink:
            notification_errors: list = []

            def __init__(self, settings):  # noqa: ANN001
                pass

            def assert_private_config(self, path):  # noqa: ANN001
                pass

            def ingest_with_status(self, payload):  # noqa: ANN001
                return payload, True

        monkeypatch.setattr(runner, "DistributedCaptureSink", Sink)
        monkeypatch.setattr(runner, "load_non_browser_jobs", lambda path: [])
        monkeypatch.setattr(runner, "preflight_optional_dependencies", lambda jobs: [])
        monkeypatch.setattr(runner, "run_phase1_rss", lambda *a, **kw: {"records_synced": 0})

        result = runner.run_phase1_laskin(
            Settings(_env_file=None, project_id="ai26"),
            study_config=tmp_path / "ai26.yaml",
            source_manifest=deployed,
            tracked_plan=broken,
            rotation=0,
        )
        assert result["status"] == "ok", "the cycle must still succeed"
        assert result["manifest_drift"] is not None
        assert "error" in result["manifest_drift"]

    def test_the_wrapper_passes_the_tracked_plan(self) -> None:
        wrapper = (
            Path(__file__).resolve().parents[1] / "scripts" / "run_ai26_laskin_collect.sh"
        ).read_text(encoding="utf-8")
        assert "--tracked-plan" in wrapper, "the cron wrapper must request the drift report"
        assert "LACLAUGPT_AI26_TRACKED_PLAN" in wrapper, "the plan path must be overridable"
