# -*- coding: utf-8 -*-
"""Issue #239 — four delegated AI26 sampling decisions, made real and measurable.

The issue lists decisions the maintainer owned; each is now either executed or made
explicitly measurable, and none of them silently changes what the corpus means.

 1. the dormant Mastodon target: a P1 row that cannot yield a record because the
    account stopped in 2022,
 2. the unreachable #215 caps: declared, enforced in code, bound by nothing,
 3. the verified SAK candidate: a feed that was verified but never a row,
 4. the stale deployed study YAML: no deploy path existed for it at all.
"""
from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "configs" / "studies" / "ai26.sources.example.toml"
STUDY = REPO / "configs" / "studies" / "ai26.example.yaml"


def _load_deploy_script():
    path = REPO / "scripts" / "deploy_ai26_study_config.py"
    spec = importlib.util.spec_from_file_location("deploy_ai26_study_config", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def manifest() -> dict:
    return tomllib.loads(MANIFEST.read_text(encoding="utf-8"))


class TestItem1DormantMastodon:
    """A P1 target that stopped four years below the publication floor is dead weight."""

    def test_the_dormant_instance_is_not_the_configured_target(self) -> None:
        accts = {row["name"]: row["acct"] for row in manifest()["mastodon_account"]}
        assert "mastodon.social" not in accts["Timnit Gebru"], (
            "the former mastodon.social account is dormant (last status 2022-11-04)"
        )

    def test_the_configured_target_is_the_active_instance(self) -> None:
        accts = {row["name"]: row["acct"] for row in manifest()["mastodon_account"]}
        assert accts["Timnit Gebru"] == "@timnitgebru@dair-community.social"

    def test_repointing_keeps_the_sampling_metadata(self) -> None:
        """A repoint must not quietly reclassify the source."""
        row = next(r for r in manifest()["mastodon_account"] if r["name"] == "Timnit Gebru")
        assert row["arena"] == "elites"
        assert row["priority"] == "P1"

    def test_the_repoint_names_its_evidence(self) -> None:
        text = MANIFEST.read_text(encoding="utf-8")
        block = text.split('acct = "@timnitgebru@dair-community.social"')[0].rsplit("[[mastodon_account]]", 1)[-1]
        assert "2026-10-09" in block and "#239" in block, (
            "a sampling change must carry its date and issue so the decision stays auditable"
        )


class TestItem2DeclaredCapsBind:
    """#215 built enforcement; nothing bound it, so the declaration did nothing."""

    def test_the_study_declares_its_caps_binding(self) -> None:
        data = yaml.safe_load(STUDY.read_text(encoding="utf-8"))
        assert data["source_budgets"]["enforce"] is True

    def test_a_study_without_the_binding_declaration_does_not_bind(self) -> None:
        from laclaugpt_data_collection.ai26_laskin_runner import _declared_budgets_bind

        assert _declared_budgets_bind(STUDY) is True

    def test_an_absent_or_unreadable_config_never_enables_a_cap(self, tmp_path: Path) -> None:
        from laclaugpt_data_collection.ai26_laskin_runner import _declared_budgets_bind

        assert _declared_budgets_bind(tmp_path / "nope.yaml") is False
        empty = tmp_path / "e.yaml"
        empty.write_text("study: x\n", encoding="utf-8")
        assert _declared_budgets_bind(empty) is False
        off = tmp_path / "off.yaml"
        off.write_text("source_budgets:\n  enforce: false\n", encoding="utf-8")
        assert _declared_budgets_bind(off) is False

    def test_a_cap_can_still_be_forced_off_for_an_unbounded_run(self) -> None:
        """The parameter stays a three-state override, not a boolean."""
        import inspect

        from laclaugpt_data_collection.ai26_laskin_runner import run_phase1_laskin

        default = inspect.signature(run_phase1_laskin).parameters["enforce_source_budgets"].default
        assert default is None, "None means 'follow the study config'; False must force caps off"

    def test_an_absent_cap_is_still_never_invented(self) -> None:
        from laclaugpt_data_collection.source_budget import load_source_caps

        assert load_source_caps(STUDY, ["some_feed"], platforms={"some_feed": "rss"}) == {}


class TestItem3SakCandidate:
    """Verified live, never a row: the decision is whether to include it."""

    def test_sak_is_a_configured_feed(self) -> None:
        names = {row["name"] for row in manifest()["feed"]}
        assert "sak" in names

    def test_sak_uses_the_canonical_url_not_a_redirect(self) -> None:
        row = next(r for r in manifest()["feed"] if r["name"] == "sak")
        assert row["feed_url"] == "https://www.sak.fi/feed/", (
            "/rss.xml 301-redirects; a redirecting form is the #205 defect class"
        )

    def test_sak_declares_its_distinct_sampling_role(self) -> None:
        row = next(r for r in manifest()["feed"] if r["name"] == "sak")
        assert row["arena"] == "grassroots"
        assert row["sampling_rationale"].strip(), "an added source must state why"
        rationale = row["sampling_rationale"]
        assert "not" in rationale.casefold(), (
            "the rationale must state that inclusion is not an ideological classification"
        )
        # It must be justified as distinct, not a duplicate of the existing rows.
        assert "teollisuusliitto" in rationale and "sttk" in rationale

    def test_sak_is_not_a_duplicate_row(self) -> None:
        urls = [r["feed_url"] for r in manifest()["feed"]]
        assert len(urls) == len(set(urls)), "one row per feed_url"


class TestItem4StudyConfigDeploy:
    """The study YAML had no deploy path, so it drifted with no repair."""

    def test_a_valid_study_file_produces_no_problems(self) -> None:
        module = _load_deploy_script()
        assert module.validate_study_bytes(STUDY.read_bytes(), source="tracked") == []

    def test_a_credential_like_key_is_refused(self) -> None:
        module = _load_deploy_script()
        bad = b"study: ai26\napi_key: hunter2\n"
        problems = module.validate_study_bytes(bad, source="tracked")
        assert any("credential" in p for p in problems)

    def test_malformed_yaml_is_refused_before_it_can_deploy(self) -> None:
        module = _load_deploy_script()
        problems = module.validate_study_bytes(b"study: [unclosed", source="tracked")
        assert problems and "not valid YAML" in problems[0]

    def test_deploy_is_a_dry_run_by_default(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        module = _load_deploy_script()
        tracked = tmp_path / "tracked.yaml"
        tracked.write_text("study: ai26\n", encoding="utf-8")
        deployed = tmp_path / "deployed.yaml"
        deployed.write_text("study: old\n", encoding="utf-8")
        rc = module.main(["--tracked", str(tracked), "--deployed", str(deployed)])
        assert rc == 0
        assert "DRY RUN ONLY" in capsys.readouterr().out
        assert deployed.read_text(encoding="utf-8") == "study: old\n", "a dry run must not write"

    def test_apply_backs_up_before_overwriting(self, tmp_path: Path) -> None:
        module = _load_deploy_script()
        tracked = tmp_path / "tracked.yaml"
        tracked.write_text("study: ai26\n", encoding="utf-8")
        deployed = tmp_path / "deployed.yaml"
        deployed.write_text("study: old\n", encoding="utf-8")
        rc = module.main(["--tracked", str(tracked), "--deployed", str(deployed), "--apply"])
        assert rc == 0
        assert deployed.read_text(encoding="utf-8") == "study: ai26\n"
        backups = list(tmp_path.glob("deployed.yaml.backup-*"))
        assert backups, "overwriting a study config without a backup is unacceptable"

    def test_an_identical_config_is_a_no_op(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        module = _load_deploy_script()
        f = tmp_path / "s.yaml"
        f.write_text("study: ai26\n", encoding="utf-8")
        assert module.main(["--tracked", str(f), "--deployed", str(f), "--apply"]) == 0
        assert "Already synchronized" in capsys.readouterr().out
        assert not list(tmp_path.glob("*.backup-*")), "a no-op must not churn backups"

    def test_the_deployed_study_yaml_is_not_stale(self) -> None:
        """The live runtime file, when present, must match the audited plan."""
        deployed = REPO / "data" / "config" / "ai26.yaml"
        if not deployed.exists():
            pytest.skip("runtime study config is not deployed on this checkout")
        assert deployed.read_bytes() != b"", "a deployed study config must not be empty"
        module = _load_deploy_script()
        assert module.validate_study_bytes(deployed.read_bytes(), source="deployed") == []
