#!/usr/bin/env python3
"""Offline contract-conformance check for the Collection module.

Collection is the first stage of the shared pipeline and therefore the module
that establishes the canonical record every sibling depends on. This tool
verifies, without network access, a live service or any research data, that the
module still honours the project-wide contracts:

* ``docs/CANONICAL_DATA_CONTRACT.md`` — ``source_url`` is the semantic identity
  and must survive canonicalization and every storage/transport round trip
  unchanged; platform/backend ids remain aliases;
* the shared cross-module parity fixture — the versioned schema-drift tripwire
  vendored at ``tests/fixtures/canonical_parity_v1.json``;
* ``docs/STORAGE_BACKEND_CONTRACT.md`` — ``auto | mongodb | csv`` semantics,
  where ``auto`` must never invent a remote destination and local CSV/SQLite
  operation stays a first-class zero-infrastructure mode.

The check is observational: it reads, reconstructs and compares. It never
contacts a service, mutates configuration or writes research data. Exit status
is 0 when every check passes and 1 otherwise, so it can gate CI directly.

Usage::

    python tools/verify_contracts.py
    python tools/verify_contracts.py --fixture /path/to/canonical_parity_v1.json
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SRC = REPOSITORY_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DEFAULT_FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "canonical_parity_v1.json"
AI26_HANDOFF_FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "ai26_phase1_handoff_v1.json"

# Normative invariants from the fixture README.
EXPECTED_SOURCE_URL = "https://example.invalid/laclaugpt/synthetic/record-001"
EXPECTED_LEGACY_ID = "legacy-001"
EXPECTED_LEGACY_FIELD = "must-survive-roundtrip"


class CheckFailure(Exception):
    """A contract invariant was violated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def _load_fixture(path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"parity fixture not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(payload, dict), "parity fixture must be a JSON object")
    return payload


def _record_from_fixture(payload: dict[str, Any]) -> Any:
    from laclaugpt_data_collection.interchange import migrate_payload
    from laclaugpt_data_collection.models import CanonicalRecord

    return CanonicalRecord.model_validate(migrate_payload(payload))


def check_fixture_construction(payload: dict[str, Any], record: Any) -> None:
    """The fixture must load through the canonical Collection record model."""
    _require(
        record.source_url == EXPECTED_SOURCE_URL,
        f"canonical identity changed during canonicalization: {record.source_url!r}",
    )
    _require(
        record.source_url == payload["source_url"],
        "canonicalization must not rewrite the fixture identity",
    )
    _require(
        record.source_native_ids.get("legacy_document_id") == EXPECTED_LEGACY_ID,
        "legacy source identifier was dropped",
    )
    _require(
        record.source.raw_metadata.get("legacy_optional_field") == EXPECTED_LEGACY_FIELD,
        "legacy optional source metadata was dropped",
    )


def check_multimodal_references_only(record: Any) -> None:
    """Optional multimodal content survives as references, never as media."""
    content = record.content
    for field in ("transcripts", "ocr", "frames"):
        values = getattr(content, field, None)
        _require(bool(values), f"{field} were dropped during canonicalization")
    _require(bool(content.media_references), "media references were dropped")

    # References must stay references: no media bytes, and any locator must be a
    # synthetic fixture/example locator rather than a real retrievable URL.
    for reference in content.media_references:
        fields = reference.model_dump()
        locators = [
            str(value)
            for key, value in fields.items()
            if value and key in {"ref", "url", "object_ref", "local_ref", "media_ref"}
        ]
        _require(
            bool(locators),
            "a media reference carries no locator at all",
        )
        for locator in locators:
            _require(
                locator.startswith("fixture://") or "example.invalid" in locator,
                f"media reference is not a synthetic fixture reference: {locator!r}",
            )


def check_review_state_is_human_controlled(record: Any) -> None:
    """Importing the fixture must not fabricate or promote review state."""
    review = record.review or {}
    _require(
        review.get("status") == "PROVISIONAL",
        "review state must remain human-controlled (fixture is PROVISIONAL)",
    )
    serialized = json.dumps(record.model_dump(mode="json"), sort_keys=True)
    _require(
        "CANDIDATE_INTERPRETATION" in serialized,
        "candidate interpretation was dropped during import",
    )


def check_round_trips(record: Any) -> list[str]:
    """JSONL, CSV, MongoDB-shape and SQLite must reconstruct the same record."""
    from laclaugpt_data_collection.interchange import (
        from_flat_row,
        from_mongo_document,
        read_csv,
        read_jsonl,
        to_flat_row,
        to_mongo_document,
        write_csv,
        write_jsonl,
    )
    from laclaugpt_data_collection.storage.local import SQLiteRecordStore

    reference = record.model_dump(mode="json")
    verified: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # flat-row projection must round trip
        restored_flat = from_flat_row(to_flat_row(record))
        _require(
            restored_flat.model_dump(mode="json") == reference,
            "flat-row projection did not reconstruct the same logical record",
        )
        verified.append("flat-row")

        jsonl_path = root / "records.jsonl"
        write_jsonl(jsonl_path, [record])
        _require(
            read_jsonl(jsonl_path)[0].model_dump(mode="json") == reference,
            "jsonl round trip did not reconstruct the same logical record",
        )
        verified.append("jsonl")

        csv_path = root / "records.csv"
        write_csv(csv_path, [record])
        _require(
            read_csv(csv_path)[0].model_dump(mode="json") == reference,
            "csv round trip did not reconstruct the same logical record",
        )
        verified.append("csv")

        # Backend-only ids must never become semantic identity.
        document = to_mongo_document(record)
        document["_id"] = "backend-only-id"
        restored_mongo = from_mongo_document(document)
        _require(
            restored_mongo.source_url == EXPECTED_SOURCE_URL,
            "mongo round trip lost the canonical identity",
        )
        _require(
            restored_mongo.model_dump(mode="json") == reference,
            "mongo document round trip did not reconstruct the same logical record",
        )
        verified.append("mongo-document")

        sqlite_path = root / "records.sqlite3"
        store = SQLiteRecordStore(sqlite_path)
        store.upsert(record)
        restored = store.get(EXPECTED_SOURCE_URL)
        _require(restored is not None, "sqlite store did not return the stored record")
        _require(
            restored is not None and restored.model_dump(mode="json") == reference,
            "sqlite round trip did not reconstruct the same logical record",
        )
        verified.append("sqlite")

    return verified


def check_backend_selector_semantics() -> None:
    """``auto`` must not invent a remote destination; explicit modes are strict.

    Only offline-observable behaviour is asserted. The check must not depend on a
    developer's local ``.env``: ``Settings`` reads it via ``env_file=".env"``, so
    an ambient MongoDB URI would otherwise make ``auto`` legitimately resolve to
    MongoDB and turn this into a machine-dependent assertion. ``auto`` is
    therefore exercised with the URI explicitly cleared, which is the state the
    contract describes ("use MongoDB only when an endpoint has been explicitly
    configured").
    """
    from laclaugpt_data_collection.config import Settings
    from laclaugpt_data_collection.factory import build_record_store
    from laclaugpt_data_collection.storage.csv import CSVRecordStore
    from laclaugpt_data_collection.storage.local import SQLiteRecordStore

    # auto with no configured endpoint must stay local, never invent one.
    auto_store = build_record_store(Settings(record_backend="auto", mongodb_uri=""))
    _require(
        isinstance(auto_store, (CSVRecordStore, SQLiteRecordStore)),
        f"auto without an endpoint must stay local, got {type(auto_store).__name__}",
    )

    # explicit csv / sqlite select local stores with no remote attempt.
    _require(
        isinstance(
            build_record_store(Settings(record_backend="csv", mongodb_uri="")),
            CSVRecordStore,
        ),
        "explicit csv selection must build the local CSV store",
    )
    _require(
        isinstance(
            build_record_store(Settings(record_backend="sqlite", mongodb_uri="")),
            SQLiteRecordStore,
        ),
        "explicit sqlite selection must build the local SQLite store",
    )

    # explicit mongodb without a URI must fail closed with a clear error.
    try:
        build_record_store(Settings(record_backend="mongodb", mongodb_uri=""))
    except (RuntimeError, ValueError):
        pass
    else:
        raise CheckFailure("explicit mongodb without a URI must fail closed")


def ambient_configuration_note() -> str | None:
    """Return a note when a local ``.env`` could make results machine-dependent.

    ``Settings`` loads ``.env`` when present, which is correct for runtime but
    makes a conformance run depend on the machine. This is reported, not failed:
    CI has no ``.env``, and the checks that matter clear the endpoint explicitly.
    """
    from laclaugpt_data_collection.config import Settings

    if not (REPOSITORY_ROOT / ".env").is_file():
        return None
    if Settings().mongodb_uri:
        return (
            "note: a local .env supplies a MongoDB endpoint; "
            "endpoint-dependent checks were run with it explicitly cleared"
        )
    return None



def check_ai26_phase1_handoff() -> None:
    """Pin the Collection -> Analysis AI26 Phase 1 boundary."""

    from laclaugpt_data_collection.models import CanonicalRecord, SCHEMA_VERSION

    payload = _load_fixture(AI26_HANDOFF_FIXTURE)
    contract_version = payload.pop("contract_version", None)
    _require(
        contract_version == "ai26-phase1-handoff-v1",
        f"unexpected AI26 handoff contract version: {contract_version!r}",
    )
    record = CanonicalRecord.model_validate(payload)

    _require(record.schema_version == SCHEMA_VERSION == "1.1.0", "AI26 schema version drifted")
    _require(record.source_url == "https://example.invalid/ai26/post/001", "AI26 source identity was lost")
    _require(
        record.source_native_ids.get("platform_post_id") == "ai26-post-001",
        "AI26 native post id was lost",
    )
    _require(record.source.created_at == "2026-09-18T09:00:00Z", "AI26 source timestamp was lost")
    _require(record.source.collected_at == "2026-09-18T09:00:05Z", "AI26 collection timestamp was lost")
    _require(record.content.text.startswith("Synthetic AI26 source text"), "AI26 text was lost")
    _require(record.source.language == "en" and record.content.language == "en", "AI26 language metadata was lost")
    _require(
        record.content.media_references[0].ref == "fixture://ai26-phase1/media/video-001",
        "AI26 media reference was lost",
    )
    _require(
        record.intermediate.frames[0]["media_ref"] == "fixture://ai26-phase1/frame/004",
        "AI26 frame reference was lost",
    )
    _require(
        record.provenance[0].metadata.get("contract_version") == contract_version,
        "AI26 handoff provenance was lost",
    )
    _require(record.analysis == {} and record.evidence == [], "Collection fixture must remain analysis-neutral")


def check_public_tree_policy() -> None:
    """The repository's own public-tree hygiene gate must pass."""
    import subprocess

    script = REPOSITORY_ROOT / "scripts" / "check_public_tree.py"
    if not script.is_file():
        raise CheckFailure(f"public-tree policy script missing: {script}")
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )
    _require(
        result.returncode == 0,
        f"public-tree policy check failed: {result.stdout.strip() or result.stderr.strip()}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline Collection contract-conformance check."
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="path to the shared canonical parity fixture",
    )
    args = parser.parse_args(argv)

    payload = _load_fixture(args.fixture)
    record = _record_from_fixture(payload)

    checks: list[tuple[str, Any]] = [
        ("fixture construction", lambda: check_fixture_construction(payload, record)),
        ("multimodal references only", lambda: check_multimodal_references_only(record)),
        (
            "review state is human-controlled",
            lambda: check_review_state_is_human_controlled(record),
        ),
        ("backend selector semantics", check_backend_selector_semantics),
        ("AI26 Phase 1 handoff", check_ai26_phase1_handoff),
        ("public-tree policy", check_public_tree_policy),
    ]

    failures: list[str] = []
    for name, check in checks:
        try:
            check()
        except CheckFailure as exc:
            failures.append(f"{name}: {exc}")
            print(f"FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - report any defect, never crash
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok    {name}")

    try:
        adapters = check_round_trips(record)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"adapter round trips: {type(exc).__name__}: {exc}")
        print(f"ERROR adapter round trips: {type(exc).__name__}: {exc}")
    else:
        print(f"ok    adapter round trips ({', '.join(adapters)})")

    if failures:
        print(f"\n{len(failures)} contract check(s) failed")
        return 1

    note = ambient_configuration_note()
    if note:
        print(note)
    print("\nall Collection contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
