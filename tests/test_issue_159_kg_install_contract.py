"""Regression tests for issue #159: documented installs must satisfy KG tests."""
from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _normalized(requirement: str) -> str:
    return (
        requirement.split("[", 1)[0]
        .split("<", 1)[0]
        .split(">", 1)[0]
        .split("=", 1)[0]
        .strip()
        .lower()
    )


def test_dev_extra_contains_knowledge_graph_test_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = project["project"]["optional-dependencies"]

    dev_names = {_normalized(req) for req in extras["dev"]}
    kg_names = {_normalized(req) for req in extras["kg"]}

    assert {"rdflib", "pyshacl"} <= kg_names
    assert {"rdflib", "pyshacl"} <= dev_names


def test_documented_pytest_paths_install_dev_extra() -> None:
    runbook = (ROOT / "docs" / "AI26_LASKIN_COLLECTION.md").read_text(encoding="utf-8")
    handoff = (ROOT / "docs" / "HERMES_AI26_LASKIN_HANDOFF.md").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    install = "pip install -e '.[distributed,phase1-non-browser,dev]'"
    assert install in runbook
    assert install in handoff
    assert "web-mining,dev]" in requirements


def test_readme_documents_full_suite_dependency_contract() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "The `dev` extra is the supported contract for running the full test suite." in readme
    assert "separate `kg` extra" in readme
