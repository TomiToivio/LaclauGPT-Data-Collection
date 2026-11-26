"""Synthetic checks of the read-only source frame acceptance audit."""
import json

import mongomock

from scripts.audit_ai26_source_frame_474_475 import audit


def test_source_frame_audit_counts_candidates_and_never_mutates():
    db = mongomock.MongoClient().fixture
    records = db.records
    base = {"project_id": "ai26", "collection_id": "ai26"}
    wrong = "https://x.com/MIRI_AI/status/123"
    records.insert_many([
        {**base, "source_url": wrong, "source": {"platform": "x", "author": "MIRI_AI"},
         "arena": "elites", "content": {"text": "private synthetic text"},
         "handoff": {"status": "ready"}},
        {**base, "source_url": "https://twitter.com/miri_ai/status/456", "source": {}},
        {**base, "source_url": "https://x.com/miri_ai/status/789",
         "source": {"platform": "x", "author": "another_actor"}},
        {**base, "source_url": "https://x.com/MIRIBerkeley/status/121",
         "source": {"platform": "x", "author": "miriberkeley"}},
        {**base, "source": {"platform": "bluesky", "author": "intelligence.org"}},
        {**base, "source_name": "us_congressional_bills", "arena": "parliamentary",
         "content": {"text": "fixture"}, "handoff": {"status": "ready", "published_at": "2026-11-26"}},
        {**base, "source": {"raw_metadata": {"source_name": "uk_ai_security_institute"}}},
        {**base, "project_id": "other", "source_url": wrong, "source": {"platform": "x"}},
    ])
    db.analysis.insert_one({"source_url": wrong})
    before = list(records.find())
    report = audit(records, db.analysis)
    assert report["historical_wrong_miri"] == {
        "records": 2, "arena_blank": 1, "ready": 1, "with_analysis": 1, "ambiguous_identity": 1,
    }
    assert report["correct_miri_x"]["records"] == 1
    assert report["miri_bluesky"]["records"] == 1
    assert report["parliamentary_sources"]["us_congressional_bills"]["usable_dated_text"] == 1
    assert report["parliamentary_sources"]["uk_ai_security_institute"]["text"] == 0
    assert list(records.find()) == before
    assert "private synthetic text" not in json.dumps(report)
    assert wrong not in json.dumps(report)
