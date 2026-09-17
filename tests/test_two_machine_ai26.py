"""Two-machine AI26 invariants (issue #60).

These tests are offline and touch only checked-in public configuration. They
lock the properties that let Localhost and Laskin share one AI26 research
design instead of drifting into machine-specific forks:

* the X browser-tour targets in the study YAML and the source manifest agree;
* the declared X budget is not smaller than the explicit target list;
* the cron wrappers resolve their own interpreter path instead of assuming
  ``laclaugpt-*`` is already on PATH (cron's PATH excludes both ``.venv/bin``
  and ``~/.local/bin``).
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "configs" / "studies" / "ai26.example.yaml"
SOURCES = ROOT / "configs" / "studies" / "ai26.sources.example.toml"

WRAPPERS = [
    "run_ai26_localhost_collect.sh",
    "run_ai26_localhost_media.sh",
    "run_ai26_localhost_sync.sh",
    "run_ai26_laskin_collect.sh",
    "run_ai26_laskin_media.sh",
]


def _study_yaml() -> dict:
    import yaml

    return yaml.safe_load(STUDY.read_text(encoding="utf-8"))


def _sources_toml() -> dict:
    return tomllib.loads(SOURCES.read_text(encoding="utf-8"))


def _yaml_x_handles(data: dict) -> list[str]:
    handles: list[str] = []
    for group in data.get("groups") or []:
        accounts = group.get("accounts") or {}
        handles.extend(accounts.get("x") or [])
    return handles


def test_x_handles_are_synchronised_between_study_yaml_and_manifest() -> None:
    """groups[].accounts.x drives /tour; the TOML x_account rows must mirror it."""
    yaml_handles = _yaml_x_handles(_study_yaml())
    toml_handles = [row["handle"] for row in _sources_toml().get("x_account") or []]

    assert yaml_handles, "study YAML must declare at least one X group target"
    assert set(yaml_handles) == set(toml_handles), (
        "AI26 X targets drifted between ai26.example.yaml and "
        "ai26.sources.example.toml; /tour reads the YAML while the manifest is "
        "the documented mirror. Update both."
    )
    assert len(yaml_handles) == len(set(yaml_handles)), "duplicate X handle in study YAML"


def test_x_budget_is_consistent_with_explicit_targets() -> None:
    """A budget below the explicit target count silently under-samples the tour."""
    data = _study_yaml()
    budget = data["source_budgets"]["x"]
    explicit = len(_yaml_x_handles(data))

    assert budget.get("explicit_target_count") == explicit, (
        "source_budgets.x.explicit_target_count must equal the actual number of "
        "configured groups[].accounts.x handles"
    )
    soft_cap = budget.get("target_accounts_soft_cap", budget.get("target_accounts"))
    assert soft_cap is not None
    assert soft_cap >= explicit, "X soft cap must not be below the explicit target count"


def test_ai26_feed_manifest_has_no_duplicate_identities() -> None:
    """Two names for one feed double-counts a source family on both machines."""
    feeds = _sources_toml()["feed"]
    urls = [f["feed_url"].rstrip("/") for f in feeds]
    names = [f["name"] for f in feeds]
    assert len(urls) == len(set(urls)), "duplicate feed_url in AI26 source manifest"
    assert len(names) == len(set(names)), "duplicate feed name in AI26 source manifest"


def test_cron_wrappers_resolve_interpreter_path_themselves() -> None:
    """Cron's PATH has neither .venv/bin nor ~/.local/bin.

    A wrapper that only checks ``command -v laclaugpt-*`` exits before running
    anything, so the schedule silently collects nothing.
    """
    runtime = (ROOT / "scripts" / "ai26_runtime.sh").read_text(encoding="utf-8")
    assert ".venv/bin" in runtime
    assert ".local/bin" in runtime

    for name in WRAPPERS:
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "ai26_runtime.sh" in text, f"{name} does not source ai26_runtime.sh"
        assert "ai26_prepend_runtime_path" in text, f"{name} does not fix PATH"
        # Every console-script guard should go through the shared helper.
        assert not re.search(r"command -v laclaugpt-", text), (
            f"{name} still uses a bare `command -v laclaugpt-*` guard, which "
            "fails under cron"
        )
