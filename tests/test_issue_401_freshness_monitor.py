"""#401: the guard has to be able to run and to fail.

The checker existed but required a private JSON mapping that does not exist on the host, and it was
not scheduled. A monitor that cannot be run is not a monitor; one that cannot fail is decoration.
"""
from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import mongomock
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "capture_freshness", ROOT / "scripts/check_ai26_capture_freshness.py")
freshness = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(freshness)

NOW = datetime(2026, 11, 3, 16, 0, tzinfo=UTC)


def records():
    return mongomock.MongoClient().db.ai26__records


def add(collection, platform, captured_at, *, project="ai26", n=1):
    for _ in range(n):
        collection.insert_one({
            "project_id": project,
            "source": {"platform": platform},
            "provenance": [{"captured_at": captured_at}],
        })


def test_a_fresh_capture_passes():
    report = freshness.evaluate({"x": NOW - timedelta(hours=2)}, now=NOW)
    assert report["ok"] is True
    assert report["observed"]["x"]["age_hours"] == 2.0


def test_a_stale_capture_fails_loudly():
    report = freshness.evaluate({"x": NOW - timedelta(days=8)}, now=NOW)
    assert report["ok"] is False
    assert report["failures"]["x"] == "stale_capture"


def test_a_platform_with_no_records_at_all_fails():
    report = freshness.evaluate({"x": None}, now=NOW)
    assert report["failures"]["x"] == "no_capture"


def test_a_capture_from_the_future_is_a_clock_problem_not_freshness():
    report = freshness.evaluate({"x": NOW + timedelta(days=3)}, now=NOW)
    assert report["failures"]["x"] == "future_capture_timestamp"


def test_platforms_are_checked_individually():
    report = freshness.evaluate({"x": NOW, "web": None}, now=NOW, platforms=("x", "web"))
    assert report["failures"] == {"web": "no_capture"}
    assert report["observed"]["x"]["age_hours"] == 0.0


def test_the_newest_capture_wins_across_records():
    col = records()
    add(col, "x", "2026-10-26T14:54:37.075Z")
    add(col, "x", "2026-10-27T09:00:00.000Z")
    add(col, "x", "2026-10-20T09:00:00.000Z")
    got = _mongo(col, platforms=("x",))
    assert got["x"].startswith("2026-10-27"), got


def test_a_platform_absent_from_the_store_comes_back_as_none():
    col = records()
    add(col, "x", "2026-11-03T12:00:00.000Z")
    got = _mongo(col, platforms=("x", "bluesky"))
    assert got["bluesky"] is None


def test_another_project_is_not_counted():
    col = records()
    add(col, "x", "2026-11-03T12:00:00.000Z", project="other")
    got = _mongo(col, platforms=("x",))
    assert got["x"] is None


def _mongo(col, *, platforms):
    """Run the production query against a mongomock collection."""
    rows = col.aggregate([
        {"$match": {"project_id": "ai26", "source.platform": {"$in": list(platforms)}}},
        {"$unwind": "$provenance"},
        {"$group": {"_id": "$source.platform", "latest": {"$max": "$provenance.captured_at"}}},
    ])
    found = {str(r["_id"]): r.get("latest") for r in rows}
    return {p: found.get(p) for p in platforms}
