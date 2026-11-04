"""Regression checks for the AI26 X provenance freshness input (#401)."""
from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import mongomock


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_ai26_capture_freshness.py"
    spec = importlib.util.spec_from_file_location("ai26_freshness_guard", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_mongo_freshness_uses_capture_not_publication_time(monkeypatch):
    module = _module()
    client = mongomock.MongoClient()
    now = datetime.now(UTC)
    client["spectacleScraper"]["ai26__records"].insert_one({
        "project_id": "ai26", "source": {"platform": "x"},
        "handoff": {"published_at": now.isoformat()},
        "provenance": [{"captured_at": (now - timedelta(days=3)).isoformat()}],
    })
    import pymongo
    # mongomock clients do not promise pymongo's context manager protocol.
    class ClientContext:
        def __enter__(self):
            return client

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(pymongo, "MongoClient", lambda *a, **kw: ClientContext())
    observed = module.mongo_capture_observations(uri="mongodb://unused")
    report = module.evaluate(observed, now=now, max_age_hours=24)
    assert report["failures"]["x"] == "stale_capture"


def test_missing_x_records_fails_closed(monkeypatch):
    module = _module()
    client = mongomock.MongoClient()
    import pymongo
    class ClientContext:
        def __enter__(self):
            return client

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(pymongo, "MongoClient", lambda *a, **kw: ClientContext())
    observed = module.mongo_capture_observations(uri="mongodb://unused")
    assert module.evaluate(observed, now=datetime.now(UTC))["failures"]["x"] == "no_capture"
