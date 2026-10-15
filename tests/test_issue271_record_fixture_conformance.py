"""#271: a schema-valid record fixture, and the claim that the version is the only difference.

The cross-repo validation the issue thread was waiting for had **no valid subject**:
every fixture in this repository fails `schemas/research-record.schema.json` (the
handoff fixtures with 9 errors each, the others with 6 to 12). So "does a Collection
record satisfy the shared schema" could not be asked, let alone answered.

This module supplies the subject and pins the two facts that were being argued in
prose:

1. a complete, synthetic record that **is** valid against the published schema;
2. its 1.2.0 twin, whose **only** schema error is the version constant -- which is
   the thread's central claim ("the mismatch is a version constant, not a schema
   shape") turned into an executable assertion;
3. the handoff fixtures, pinned as **handoff documents** with the exact fields they
   lack, so no reader mistakes one for a record again.

Nothing here changes a version constant, migrates data, or rewrites a fixture that
other tests depend on.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[1] / "schemas" / "research-record.schema.json").read_text(
        encoding="utf-8"
    )
)
VALIDATOR = Draft202012Validator(SCHEMA)
RECORD_FIXTURE = FIXTURES / "ai26_record_v1.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def error_paths(document: dict) -> set[tuple[str, ...]]:
    return {tuple(str(part) for part in error.path) for error in VALIDATOR.iter_errors(document)}


# --------------------------------------------------------------------------- #
# 1. a valid subject for cross-repo validation
# --------------------------------------------------------------------------- #


def test_the_complete_record_fixture_validates_against_the_published_schema() -> None:
    errors = sorted(VALIDATOR.iter_errors(load(RECORD_FIXTURE)), key=lambda e: list(e.path))
    assert errors == [], [f"{list(e.path) or '(root)'}: {e.message}" for e in errors]


def test_the_complete_record_fixture_declares_every_required_top_level_field() -> None:
    record = load(RECORD_FIXTURE)
    missing = sorted(set(SCHEMA["required"]) - set(record))
    assert missing == [], f"the fixture is not a record: missing {missing}"


# --------------------------------------------------------------------------- #
# 2. the claim the thread argued in prose, as an assertion
# --------------------------------------------------------------------------- #


def test_the_1_2_0_twin_differs_only_in_the_version_constant() -> None:
    """Same shape, one error: the constant. This is why no migration is implied."""
    twin = load(RECORD_FIXTURE)
    twin["schema_version"] = "1.2.0"

    errors = sorted(VALIDATOR.iter_errors(twin), key=lambda e: list(e.path))
    assert error_paths(twin) == {("schema_version",)}, (
        f"a 1.2.0 record differs from 1.1.0 somewhere other than the version: "
        f"{[f'{list(e.path) or chr(40)}: {e.message}' for e in errors]}"
    )
    assert "1.1.0" in errors[0].message  # the schema expects the older constant


def test_the_two_versions_carry_the_same_field_set() -> None:
    record = load(RECORD_FIXTURE)
    twin = dict(record, schema_version="1.2.0")
    assert sorted(record) == sorted(twin)
    assert {k: v for k, v in record.items() if k != "schema_version"} == {
        k: v for k, v in twin.items() if k != "schema_version"
    }


# --------------------------------------------------------------------------- #
# 3. the handoff fixtures are handoff documents, and the gap is enumerated
# --------------------------------------------------------------------------- #

#: Measured 2026-10-15 against ``schemas/research-record.schema.json``. The two
#: handoff fixtures are documents from *different* stages -- a completed Phase 1
#: analysis handoff and a pre-analysis collection handoff -- which is why they do
#: not share a shape. Neither is a record, and neither is meant to be.
HANDOFF_SHAPES = {
    "ai26_phase1_handoff_v1.json": {
        "missing_required": ["human_readable"],
        "keys_not_record_properties": ["alignments", "contract_version", "source_units"],
    },
    "ai26_collection_handoff_v1.json": {
        "missing_required": ["intermediate", "legacy"],
        "keys_not_record_properties": ["alignments", "fixture_version", "handoff", "source_units"],
    },
}


@pytest.mark.parametrize("name", sorted(HANDOFF_SHAPES))
def test_the_handoff_fixtures_are_handoff_documents_not_records(name: str) -> None:
    """They *should* fail record validation; what matters is that the gap is explicit.

    A reader who finds 9 schema errors against a fixture needs to know in one place
    whether that is drift or shape. This test is that place.
    """
    expected = HANDOFF_SHAPES[name]
    document = load(FIXTURES / name)

    assert error_paths(document), (
        f"{name} now validates as a record; if that is deliberate, move it out of the "
        "handoff fixtures and out of this table"
    )
    assert sorted(set(SCHEMA["required"]) - set(document)) == expected["missing_required"]
    assert sorted(set(document) - set(SCHEMA["properties"])) == expected["keys_not_record_properties"]


@pytest.mark.parametrize("name", sorted(HANDOFF_SHAPES))
def test_the_handoff_only_fields_are_not_record_properties(name: str) -> None:
    """The boundary between the two shapes, asserted rather than described."""
    for field in HANDOFF_SHAPES[name]["keys_not_record_properties"]:
        assert field not in SCHEMA["properties"], (
            f"{field} became a record property; the handoff/record boundary moved and "
            "this table needs re-measuring"
        )


def test_no_fixture_in_the_repository_is_left_without_a_valid_subject() -> None:
    """The gap that made the original question unanswerable.

    Before this change every fixture in the repository failed the published schema,
    so "does a Collection record satisfy it" had no valid subject anywhere in the
    corpus. There is now exactly one, and it stays green.
    """
    assert not list(VALIDATOR.iter_errors(load(RECORD_FIXTURE)))
