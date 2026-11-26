"""The account correction must not alter raw source identity or other studies."""
from copy import deepcopy

import mongomock
import pytest

from laclaugpt_data_collection.ai26_source_frame import MIRI_WRONG_ACCOUNT_REASON
from laclaugpt_data_collection.handoff import build_handoff
from scripts.reconcile_ai26_wrong_miri_handoffs import reconcile


def record(handle="MIRI_AI", *, author="miri_ai", platform="x", number=123):
    return {
        "project_id": "ai26", "collection_id": "ai26",
        "source_url": f"https://x.com/{handle}/status/{number}",
        "source": {"platform": platform, "author": author, "created_at": "2026-11-25T00:00:00Z"},
        "content": {"text": "synthetic fixture"},
    }


@pytest.mark.parametrize("platform,author", [("x", "MIRI_AI"), ("", ""), ("twitter", "@miri_ai")])
def test_excludes_proven_wrong_account(platform, author):
    row = record(platform=platform, author=author)
    before = deepcopy(row)
    result = build_handoff(row, project_id="ai26")
    assert (result["status"], result["reason"]) == ("excluded", MIRI_WRONG_ACCOUNT_REASON)
    assert row == before


@pytest.mark.parametrize("row", [
    record("MIRIBerkeley", author="miriberkeley"),
    record(author="another"),
    record(platform="bluesky"),
    {**record(), "collection_id": "other"},
    {**record(), "source_url": "https://example.invalid/MIRI_AI/status/123"},
])
def test_no_exclusion_for_conflicting_or_unrelated_identity(row):
    assert build_handoff(row)["reason"] != MIRI_WRONG_ACCOUNT_REASON


def test_repair_dry_run_idempotent_preserves_provenance_and_results():
    db = mongomock.MongoClient().fixture
    for number in (123, 456):
        row = record(number=number)
        row["handoff"] = {**build_handoff(row), "status": "ready", "reason": "source_ready"}
        db.records.insert_one(row)
    db.analysis.insert_one({"source_url": record(number=456)["source_url"]})
    before = list(db.records.find())
    assert reconcile(db.records, db.analysis)["eligible"] == 1
    assert list(db.records.find()) == before
    result = reconcile(db.records, db.analysis, apply=True)
    assert result["updated"] == result["with_analysis"] == 1
    after = list(db.records.find())
    assert after[0]["handoff"]["reason"] == MIRI_WRONG_ACCOUNT_REASON
    assert {k: v for k, v in after[0].items() if k != "handoff"} == {
        k: v for k, v in before[0].items() if k != "handoff"
    }
    assert after[1] == before[1]
    assert reconcile(db.records, db.analysis, apply=True)["updated"] == 0
