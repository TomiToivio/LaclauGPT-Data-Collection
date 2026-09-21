#!/usr/bin/env python3
"""Standalone CI-safe verifier for Phase 1 AI26 + Brazil26 integration fixture."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "phase1_e2e_ai26_brazil26_v1.json"


def identity(row: dict) -> tuple[str, str, str]:
    return row["project_id"], row["collection_id"], row["record"]["source_url"]


def main() -> int:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = payload["records"]
    assert payload["contract"]["canonical_schema_version"] == "1.1.0"
    assert payload["topology"]["laskin"]["browser"] == []
    assert len(rows) == 4
    assert {row["collection_id"] for row in rows} == {"ai26", "brazil26"}
    assert len({identity(row) for row in rows}) == 4

    shared = [row for row in rows if row["record"]["source_url"].endswith("/shared/phase1")]
    assert len(shared) == 2
    assert len({identity(row) for row in shared}) == 2

    ids = {
        hashlib.sha256(
            ("\0".join(identity(row)) + "\0phase1-analysis-v1").encode("utf-8")
        ).hexdigest()
        for row in rows
    }
    assert len(ids) == 4

    for row in rows:
        meta = row["record"]["provenance"][0]["metadata"]
        assert meta["project_id"] == row["project_id"]
        assert meta["collection_id"] == row["collection_id"]
        if row["machine"] == "laskin":
            assert row["execution"] == "non-browser"
            assert row["record"]["source"]["platform"].lower() not in {
                "x", "instagram", "tiktok", "firefox"
            }

    print("Phase 1 AI26 + Brazil26 integration fixture: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
