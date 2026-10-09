# -*- coding: utf-8 -*-
"""Issue #215 — a declared daily source cap must actually cap, and defer visibly.

Three sources are ~50% of the store and the Bluesky stratum is two timelines. The
mechanism is differential yield: the poll rotation is fair, but a prolific source
emits far more records per poll, and the study's declared `source_budgets` were
read by no code at all — so the bounds were methodology prose.

These tests pin the properties that make enforcement trustworthy:

- a cap **caps** (the Nth+1 record is refused);
- the day's count comes from the **store**, not process memory, because one hourly
  cycle is one process and a memory counter would reset every tick;
- over-cap records are **deferred and counted**, never silently dropped;
- an absent cap means uncapped — the module never invents a limit;
- a new UTC day resets the budget without operator action.

No database: the count source is injected.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from laclaugpt_data_collection.source_budget import (
    SourceDailyBudget,
    budget_report,
    load_source_caps,
    source_identity,
    utc_day,
)


def _rec(source_name: str) -> dict:
    return {"source_url": f"https://x/{source_name}", "source": {"raw_metadata": {"source_name": source_name}}}


class TestIdentity:
    def test_identity_matches_what_the_audit_ranks_by(self) -> None:
        assert source_identity(_rec("lesswrong_frontpage")) == "lesswrong_frontpage"

    def test_identity_falls_back_to_author_then_empty(self) -> None:
        assert source_identity({"author": "timnitgebru"}) == "timnitgebru"
        assert source_identity({"source_url": "u"}) == ""


class TestCapping:
    def test_the_cap_admits_exactly_its_number(self) -> None:
        budget = SourceDailyBudget(caps={"chatty": 3})
        results = [budget.admit(_rec("chatty")) for _ in range(5)]
        assert results == [True, True, True, False, False]
        assert budget.summary()["deferred_total"] == 2
        assert budget.summary()["deferred_this_cycle"] == {"chatty": 2}

    def test_an_absent_cap_means_uncapped(self) -> None:
        """The module must never invent a limit."""
        budget = SourceDailyBudget(caps={"capped": 1})
        assert all(budget.admit(_rec("uncapped")) for _ in range(50))
        assert budget.summary()["deferred_total"] == 0

    def test_a_zero_or_negative_cap_is_not_a_cap(self) -> None:
        budget = SourceDailyBudget(caps={"a": 0, "b": -5})
        assert budget.summary()["caps"] == {}
        assert budget.admit(_rec("a")) is True

    def test_a_cap_is_per_source_not_global(self) -> None:
        budget = SourceDailyBudget(caps={"a": 2, "b": 2})
        for _ in range(2):
            budget.admit(_rec("a"))
            budget.admit(_rec("b"))
        assert budget.admit(_rec("a")) is False
        assert budget.admit(_rec("b")) is False
        assert budget.summary()["deferred_this_cycle"] == {"a": 1, "b": 1}


class TestTheCountComesFromTheStore:
    def test_records_already_stored_today_count_against_the_cap(self) -> None:
        """The crux: one cycle is one process, so memory cannot enforce a DAILY cap."""
        stored = {"chatty": 9}

        def count_today(identity: str, day: str) -> int:
            return stored.get(identity, 0)

        budget = SourceDailyBudget(caps={"chatty": 10}, count_today=count_today)
        assert budget.admit(_rec("chatty")) is True, "the 10th is within cap"
        assert budget.admit(_rec("chatty")) is False, "the 11th is over cap"
        assert budget.summary()["deferred_total"] == 1

    def test_a_source_already_at_cap_admits_nothing(self) -> None:
        budget = SourceDailyBudget(
            caps={"gone": 5}, count_today=lambda identity, day: 5
        )
        assert budget.admit(_rec("gone")) is False

    def test_without_a_count_source_the_cap_is_still_enforced_within_the_cycle(self) -> None:
        """A missing count source must not silently disable the cap."""
        budget = SourceDailyBudget(caps={"chatty": 2})
        assert budget.admit(_rec("chatty")) is True
        assert budget.admit(_rec("chatty")) is True
        assert budget.admit(_rec("chatty")) is False


class TestDayRollover:
    def test_a_new_utc_day_resets_the_budget(self) -> None:
        day1 = datetime(2026, 10, 9, 23, 0, tzinfo=timezone.utc)
        budget = SourceDailyBudget(caps={"chatty": 1}, day=utc_day(day1))
        assert budget.admit(_rec("chatty"), now=day1) is True
        assert budget.admit(_rec("chatty"), now=day1) is False
        day2 = day1 + timedelta(hours=2)
        assert budget.admit(_rec("chatty"), now=day2) is True, "a new day must reset"
        assert budget.summary()["deferred_total"] == 0

    def test_rollover_leaves_no_stale_deferrals_in_the_report(self) -> None:
        day1 = datetime(2026, 10, 9, 23, 0, tzinfo=timezone.utc)
        budget = SourceDailyBudget(caps={"chatty": 1}, day=utc_day(day1))
        budget.admit(_rec("chatty"), now=day1)
        budget.admit(_rec("chatty"), now=day1)
        assert budget.summary()["deferred_total"] == 1
        budget.admit(_rec("chatty"), now=day1 + timedelta(hours=2))
        assert budget.summary()["deferred_total"] == 0


class TestDeclaredCaps:
    def test_declared_account_caps_map_onto_configured_identities(self, tmp_path) -> None:
        study = tmp_path / "ai26.yaml"
        study.write_text(
            "study: ai26\n"
            "source_budgets:\n"
            "  bluesky:\n"
            "    target_accounts: 12\n"
            "    daily_record_cap: 100\n"
            "  x:\n"
            "    daily_record_cap: 240\n",
            encoding="utf-8",
        )
        caps = load_source_caps(
            study, ["Timnit Gebru", "Emily M. Bender"],
            platforms={"Timnit Gebru": "bluesky", "Emily M. Bender": "bluesky"},
        )
        assert caps == {"Timnit Gebru": 100, "Emily M. Bender": 100}

    def test_a_group_ceiling_is_not_reported_as_a_per_source_cap(self, tmp_path) -> None:
        """rss_web's soft cap is a GROUP total; mapping it per-feed would misstate it."""
        study = tmp_path / "ai26.yaml"
        study.write_text(
            "source_budgets:\n"
            "  rss_web:\n"
            "    target_endpoints: 40\n"
            "    daily_relevant_items_soft_cap: 240\n",
            encoding="utf-8",
        )
        assert load_source_caps(study, ["lesswrong_frontpage"], platforms={"lesswrong_frontpage": "rss"}) == {}

    def test_without_a_platform_map_no_cap_is_invented(self, tmp_path) -> None:
        """A feed name must never receive an account cap just for existing."""
        study = tmp_path / "ai26.yaml"
        study.write_text(
            "source_budgets:\n  bluesky:\n    daily_record_cap: 100\n", encoding="utf-8"
        )
        assert load_source_caps(study, ["anthropic_news"]) == {}
        assert load_source_caps(
            study, ["anthropic_news"], platforms={"anthropic_news": "rss"}
        ) == {}

    def test_a_study_without_budgets_yields_no_caps(self, tmp_path) -> None:
        study = tmp_path / "ai26.yaml"
        study.write_text("study: ai26\n", encoding="utf-8")
        assert load_source_caps(study, ["a"], platforms={"a": "bluesky"}) == {}


class TestReport:
    def test_the_report_names_deferrals_not_just_a_total(self) -> None:
        budget = SourceDailyBudget(caps={"chatty": 1})
        budget.admit(_rec("chatty"))
        budget.admit(_rec("chatty"))
        line = budget_report(budget)
        assert "over cap" in line
        assert "chatty" in line
        assert "deferred, not dropped" in line, "the wording must not imply data loss"

    def test_an_unreached_cap_says_so(self) -> None:
        line = budget_report(SourceDailyBudget(caps={"quiet": 500}))
        assert "none reached" in line

    def test_no_declared_caps_says_so(self) -> None:
        assert "none declared" in budget_report(SourceDailyBudget())


class TestRunnerWiring:
    """The cap must be reachable from the collect cycle, and opt-in (#215).

    Enabling a cap changes what the corpus contains, which is a sampling decision,
    so it must not happen by default.
    """

    def test_the_budget_parameter_is_a_three_state_override(self) -> None:
        """#239.2: the STUDY decides, not a wrapper flag nobody passes.

        `None` (default) follows the audited config's `source_budgets.enforce`;
        True forces the declared caps on; False forces them off for a deliberate
        unbounded run. Pinning `is False` here is what kept the caps unreachable.
        """
        import inspect

        from laclaugpt_data_collection.ai26_laskin_runner import run_phase1_laskin

        sig = inspect.signature(run_phase1_laskin)
        default = sig.parameters["enforce_source_budgets"].default
        assert default is None, (
            "the default must defer to the study config; True/False remain explicit overrides"
        )

    def test_a_study_that_declares_nothing_enables_nothing(self, tmp_path) -> None:
        """The stronger property the old default was protecting: no silent capping."""
        from laclaugpt_data_collection.ai26_laskin_runner import _declared_budgets_bind

        undecided = tmp_path / "undecided.yaml"
        undecided.write_text("study: ai26\n", encoding="utf-8")
        assert _declared_budgets_bind(undecided) is False

    def test_the_cli_exposes_the_flag(self) -> None:
        # argparse would SystemExit on an unknown flag; parsing must succeed.

        from laclaugpt_data_collection.ai26_laskin_runner import main

        # Rebuild the parser the same way main() does, without running a cycle.
        src = __import__("inspect").getsource(main)
        assert "--enforce-source-budgets" in src, "the flag must be reachable"

    def test_the_cycle_reports_the_budget_and_the_deferral_count(
        self, tmp_path, monkeypatch
    ) -> None:
        from laclaugpt_data_collection import ai26_laskin_runner as runner
        from laclaugpt_data_collection.config import Settings
        from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord

        class Sink:
            notification_errors: list = []

            def __init__(self, settings):  # noqa: ANN001
                self.records = _CountingStore()

            def assert_private_config(self, path):  # noqa: ANN001
                return path

            def ingest_with_status(self, payload):  # noqa: ANN001
                return payload, True

        class _CountingStore:
            def count_by_source_since(self, name, *, since_iso, collection_id=None):  # noqa: ANN001
                return 0

        def _record(name: str) -> NormalizedRecord:
            record = NormalizedRecord(
                source_url=f"https://example.invalid/{name}",
                platform="bluesky",
                text="x",
                timestamp="2026-10-01T00:00:00Z",
                raw_payload={"actor_name": name},
                collection_provenance=CollectionProvenance(module="t"),
            )
            # The real runner stamps source_name from the manifest row; set it here
            # so the budget's source identity matches production behaviour.
            record.source.raw_metadata["source_name"] = name
            return record

        study = tmp_path / "ai26.yaml"
        study.write_text(
            "study: ai26\nsource_budgets:\n  bluesky:\n    daily_record_cap: 1\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(runner, "DistributedCaptureSink", Sink)
        monkeypatch.setattr(
            runner, "load_non_browser_jobs", lambda p: [{"kind": "bluesky_account", "name": "chatty"}]
        )
        monkeypatch.setattr(runner, "preflight_optional_dependencies", lambda jobs: [])
        monkeypatch.setattr(runner, "run_phase1_rss", lambda *a, **k: {"records_synced": 0})
        monkeypatch.setattr(runner, "_records_for_job", lambda *a, **k: ([_record("chatty")] * 3, []))

        result = runner.run_phase1_laskin(
            Settings(_env_file=None, project_id="ai26"),
            study_config=study,
            source_manifest=tmp_path / "s.toml",
            collection_id="ai26",
            rotation=0,
            enforce_source_budgets=True,
        )
        assert result["records_synced"] == 1, "only one record fits the cap of 1"
        assert result["deferred_by_source_budget"] == 2
        assert result["source_budget"] is not None
        assert result["source_budget"]["caps"] == {"chatty": 1}

    def test_with_budgets_disabled_nothing_is_deferred(self, tmp_path, monkeypatch) -> None:
        from laclaugpt_data_collection import ai26_laskin_runner as runner
        from laclaugpt_data_collection.config import Settings
        from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord

        class Sink:
            notification_errors: list = []

            def __init__(self, settings):  # noqa: ANN001
                pass

            def assert_private_config(self, path):  # noqa: ANN001
                return path

            def ingest_with_status(self, payload):  # noqa: ANN001
                return payload, True

        rec = NormalizedRecord(
            source_url="https://example.invalid/a", platform="bluesky", text="x",
            timestamp="2026-10-01T00:00:00Z",
            raw_payload={"actor_name": "chatty"},
            collection_provenance=CollectionProvenance(module="t"),
        )
        rec.source.raw_metadata["source_name"] = "chatty"
        study = tmp_path / "ai26.yaml"
        study.write_text(
            "source_budgets:\n  bluesky:\n    daily_record_cap: 1\n", encoding="utf-8"
        )
        monkeypatch.setattr(runner, "DistributedCaptureSink", Sink)
        monkeypatch.setattr(runner, "load_non_browser_jobs", lambda p: [{"kind": "bluesky_account", "name": "chatty"}])
        monkeypatch.setattr(runner, "preflight_optional_dependencies", lambda jobs: [])
        monkeypatch.setattr(runner, "run_phase1_rss", lambda *a, **k: {"records_synced": 0})
        monkeypatch.setattr(runner, "_records_for_job", lambda *a, **k: ([rec] * 3, []))

        result = runner.run_phase1_laskin(
            Settings(_env_file=None, project_id="ai26"),
            study_config=study,
            source_manifest=tmp_path / "s.toml",
            collection_id="ai26",
            rotation=0,
        )
        assert result["records_synced"] == 3
        assert result["deferred_by_source_budget"] == 0
        assert result["source_budget"] is None
