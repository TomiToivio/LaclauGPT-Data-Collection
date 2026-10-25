"""corpus-audit must never present a sample's share as the corpus's share (#353).

`--limit` was applied inside the read, before the audit saw anything, so the report
could not know it had been clipped. On the live store the default turned a 9,375-record
corpus into a 5,000-record sample and every percentage in the report was a percentage of
a sample presented as a percentage of the corpus. The numbers were internally consistent,
summed to 1, and were computed over the wrong population.

This is worse than a display bug because the tool exists to make sampling findings
readable, and #336/#340/#342 were all decisions that a clipped denominator can mis-decide.
It is also silent in the direction that hides growth: as the corpus grows past the limit,
a stratum can look like it is shrinking when it is only being outgrown.
"""
from __future__ import annotations

import argparse
import json
import sys
import types

import pytest

from laclaugpt_data_collection.cli import _corpus_audit
from laclaugpt_data_collection.corpus_audit import audit_summary


def _record(index: int, arena: str = "elites") -> dict:
    return {
        "source_url": f"https://example.invalid/{index}",
        "source": {"platform": "rss", "raw_metadata": {"arena": arena, "source_name": "s"}},
        "content": {"text": "text"},
        "handoff": {"status": "ready", "published_at": "2026-10-20T00:00:00Z"},
    }


class _FakeCollection:
    def __init__(self, records: list[dict], available: int | None = None):
        self._records = records
        self._available = len(records) if available is None else available

    def count_documents(self, query: dict) -> int:
        return self._available

    def find(self, query: dict, projection: dict):
        return _FakeCursor(self._records)


class _FakeCursor:
    def __init__(self, records: list[dict]):
        self._records = records
        self._limit: int | None = None

    def limit(self, value: int):
        self._limit = value
        return self

    def __iter__(self):
        return iter(self._records[: self._limit] if self._limit is not None else self._records)


def _args(**overrides) -> argparse.Namespace:
    base = dict(
        records=None,
        mongodb_uri="mongodb://synthetic",
        mongodb_database="db",
        mongodb_collection="ai26__records",
        project="ai26",
        limit=None,
        top_n=3,
        publication_floor="2026-09-01",
        study_config=None,
        configured_sources=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


@pytest.fixture()
def fake_mongo(monkeypatch):
    store = {"records": [_record(i) for i in range(5)], "available": 5}

    class _Database:
        def __getitem__(self, name):
            return _FakeCollection(store["records"], store["available"])

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __getitem__(self, name):
            return _Database()

    module = types.ModuleType("pymongo")
    module.MongoClient = _Client
    monkeypatch.setitem(sys.modules, "pymongo", module)
    return store


def test_a_bound_limit_reports_the_population_and_the_truncation(fake_mongo, capsys):
    fake_mongo["available"] = 5000
    fake_mongo["records"] = [_record(i) for i in range(5000)]

    assert _corpus_audit(_args(limit=100)) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert report["records_available"] == 5000
    assert report["records_scanned"] == 100
    assert report["truncated"] is True
    assert report["shares_basis"] == "sample"
    # The percentages must not be silently labelled as corpus shares.
    assert "TRUNCATED" in captured.err
    assert "SAMPLE" in captured.err
    assert report["total"] == 100


def test_no_limit_audits_the_whole_population(fake_mongo, capsys):
    fake_mongo["available"] = 5

    assert _corpus_audit(_args(limit=None)) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert report["records_scanned"] == 5
    assert report["records_available"] == 5
    assert report["truncated"] is False
    assert report["shares_basis"] == "population"
    assert "TRUNCATED" not in captured.err


def test_a_limit_that_does_not_bind_is_not_reported_as_truncation(fake_mongo, capsys):
    """A limit larger than the population is not a sample; do not cry wolf."""
    fake_mongo["available"] = 3
    fake_mongo["records"] = [_record(i) for i in range(3)]

    assert _corpus_audit(_args(limit=1000)) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["truncated"] is False
    assert report["shares_basis"] == "population"


def test_the_summary_leads_with_the_denominator_when_clipped():
    """A reader who sees only the stderr line must still learn it was a sample."""
    report = {
        "total": 100,
        "records_scanned": 100,
        "records_available": 5000,
        "limit": 100,
        "truncated": True,
        "configured_sources": {"checked": False},
        "by_arena": {"shares": {"grassroots": 0.1}, "unknown": 5},
        "by_language": {"unlabelled": 2},
        "by_arena_language": {"arenas": {}},
        "by_platform": {"declared_but_empty": []},
        "concentration": {"top_n": 3, "top_n_share": 0.5},
    }
    line = audit_summary(report)

    assert line.startswith("TRUNCATED")
    assert "100 of 5000" in line
    assert "SAMPLE" in line


def test_the_summary_is_unchanged_when_not_clipped():
    report = {
        "total": 5,
        "records_scanned": 5,
        "records_available": 5,
        "limit": None,
        "truncated": False,
        "configured_sources": {"checked": False},
        "by_arena": {"shares": {"grassroots": 0.0}, "unknown": 0},
        "by_language": {"unlabelled": 0},
        "by_arena_language": {"arenas": {}},
        "by_platform": {"declared_but_empty": []},
        "concentration": {"top_n": 3, "top_n_share": 0.0},
    }
    line = audit_summary(report)

    assert not line.startswith("TRUNCATED")
    assert line.startswith("corpus audit: 5 records")
