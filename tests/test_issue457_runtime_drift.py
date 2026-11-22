"""#468 conflict reconciliation: guard newly named package schema files too.

The original branch's filename-based safety net is incorporated without
replacing the merged #457 gate's machine-readable status or fail-closed policy.
"""
from __future__ import annotations

import pytest

from scripts.check_ai26_runtime import is_schema_affecting_path


@pytest.mark.parametrize(
    "path",
    [
        "src/laclaugpt_data_collection/models.py",
        "src/laclaugpt_data_collection/canonical.py",
        "src/laclaugpt_data_collection/analysis_schema_compat.py",
        "schemas/research.schema.json",
        "src/laclaugpt_data_collection/record_schema.py",
        "src/laclaugpt_data_collection/new_model_contract.py",
        "src/laclaugpt_data_collection/other_canonical_rules.py",
    ],
)
def test_guard_schema_affecting_paths(path: str) -> None:
    assert is_schema_affecting_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "docs/schema-notes.md",
        "tests/test_schema.py",
        "src/laclaugpt_data_collection/collectors/rss.py",
        "src/laclaugpt_data_collection/server_runner.py",
        "scripts/run_ai26_laskin_collect.sh",
    ],
)
def test_allow_non_schema_paths(path: str) -> None:
    assert not is_schema_affecting_path(path)
