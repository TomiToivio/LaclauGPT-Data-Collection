# -*- coding: utf-8 -*-
"""Unit tests for the one-time AI26 provenance backfill tool (#250).

These exercise the pure resolution/plan logic against a tiny in-memory store so
no MongoDB connection is required.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "configs" / "studies" / "ai26.sources.example.toml"


def _load_tool():
    path = REPO / "tools" / "backfill_ai26_provenance.py"
    spec = importlib.util.spec_from_file_location("backfill_ai26_provenance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, matched: int, modified: int) -> None:
        self.matched_count = matched
        self.modified_count = modified


class _FakeCollection:
    """Minimal stand-in honouring only the query shapes the tool issues."""

    def __init__(self, docs: list[dict]) -> None:
        self.docs = docs
        self.updates: list[tuple] = []

    def _matches(self, doc: dict, query: dict) -> bool:
        if doc.get("project_id") != query.get("project_id"):
            return False
        if doc.get("arena") != query.get("arena", doc.get("arena")):
            return False
        platform = query.get("source.platform")
        if isinstance(platform, dict):
            if (doc.get("source") or {}).get("platform") not in platform["$in"]:
                return False
        backfill = query.get("source.backfill")
        if isinstance(backfill, dict) and (doc.get("source") or {}).get("backfill") == backfill["$ne"]:
            return False
        return True

    def find(self, query: dict) -> list[dict]:
        return [d for d in self.docs if self._matches(d, query)]

    def count_documents(self, query: dict) -> int:
        return len(self.find(query))

    def update_one(self, flt: dict, update: dict) -> _Result:
        doc = next(d for d in self.docs if d["_id"] == flt["_id"])
        changed = 0
        for key, value in update["$set"].items():
            node = doc
            parts = key.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            if node.get(parts[-1]) != value:
                node[parts[-1]] = value
                changed = 1
        self.updates.append((flt["_id"], update["$set"]))
        return _Result(matched=1, modified=changed)


def _rss_doc(doc_id: str, name: str, url: str) -> dict:
    return {
        "_id": doc_id,
        "project_id": "ai26",
        "arena": "",
        "source_url": url,
        "source": {
            "platform": "rss",
            "author": "",
            "collector": "",
            "raw_ref": None,
            "raw_metadata": {"source_name": name},
        },
        "provenance": [{"visited_url": url, "metadata": {"source_name": name}}],
    }


def _web_doc(doc_id: str) -> dict:
    return {
        "_id": doc_id,
        "project_id": "ai26",
        "arena": "",
        "source_url": "https://example.invalid/x",
        "source": {"platform": "web", "author": "", "collector": "", "raw_ref": None, "raw_metadata": {}},
        "provenance": [{"visited_url": "https://example.invalid/x", "metadata": {}}],
    }


def test_manifest_rows_carry_arena_and_collector() -> None:
    tool = _load_tool()
    rows = tool.load_manifest_rows(MANIFEST)
    by_name = {row["name"]: row for row in rows}
    assert by_name["lesswrong_frontpage"]["arena"] == "elites"
    assert by_name["lesswrong_frontpage"]["collector"] == "rss-feedparser"
    # A row that declares no arena resolves to no arena (#250 must not guess).
    assert by_name["interconnects"]["arena"] == ""


def test_resolve_by_name_with_url_corroboration_is_high_confidence() -> None:
    tool = _load_tool()
    rows = tool.load_manifest_rows(MANIFEST)
    doc = _rss_doc("1", "lesswrong_frontpage", "https://www.lesswrong.com/feed.xml?view=frontpage")
    signals = tool._document_signals(doc)
    row, confidence, _ = tool.resolve_row(rows, signals)
    assert row is not None and row["name"] == "lesswrong_frontpage"
    assert confidence == "high"


def test_resolve_returns_none_when_nothing_matches() -> None:
    tool = _load_tool()
    rows = tool.load_manifest_rows(MANIFEST)
    row, confidence, _ = tool.resolve_row(rows, tool._document_signals(_web_doc("9")))
    assert row is None
    assert confidence == "none"


def test_apply_sets_provenance_arena_and_markers() -> None:
    tool = _load_tool()
    rows = tool.load_manifest_rows(MANIFEST)
    col = _FakeCollection(
        [
            _rss_doc("a", "lesswrong_frontpage", "https://www.lesswrong.com/feed.xml?view=frontpage"),
            _rss_doc("b", "interconnects", "https://www.interconnects.ai/feed"),
            _web_doc("c"),
        ]
    )
    plan = tool.build_plan(col, rows)
    summary = tool._summarize(plan)
    assert summary == {
        "total": 3,
        "rss": 2,
        "web": 1,
        "resolved_to_arena": 1,
        "resolved_arena_less": 1,
        "resolved_total": 2,
        "unattributed": 1,
    }

    result = tool.apply_backfill(col, plan, "20260101T000000Z")
    assert result == {"matched": 3, "modified": 3}

    arena_doc = next(d for d in col.docs if d["_id"] == "a")
    assert arena_doc["arena"] == "elites"
    assert arena_doc["source"]["raw_metadata"]["arena"] == "elites"
    assert arena_doc["source"]["raw_ref"] == "ai26.sources.example.toml#feed:lesswrong_frontpage"
    assert arena_doc["source"]["collector"] == "rss-feedparser"
    assert arena_doc["source"]["backfill"] == "#250"
    assert arena_doc["source"]["backfilled_at"] == "20260101T000000Z"

    # The arena-less and unattributed documents keep arena == "" and are marked.
    arena_less = next(d for d in col.docs if d["_id"] == "b")
    assert arena_less["arena"] == ""
    assert arena_less["source"]["raw_ref"] == "ai26.sources.example.toml#feed:interconnects"

    unattr = next(d for d in col.docs if d["_id"] == "c")
    assert unattr["arena"] == ""
    assert unattr["source"]["unattributed"] is True
    assert unattr["source"]["unattributed_reason"].startswith("#250:")


def test_apply_is_idempotent() -> None:
    tool = _load_tool()
    rows = tool.load_manifest_rows(MANIFEST)
    col = _FakeCollection(
        [
            _rss_doc("a", "lesswrong_frontpage", "https://www.lesswrong.com/feed.xml?view=frontpage"),
            _web_doc("c"),
        ]
    )
    first = tool.apply_backfill(col, tool.build_plan(col, rows), "20260101T000000Z")
    assert first == {"matched": 2, "modified": 2}
    # A second pass finds nothing left to do.
    second = tool.apply_backfill(col, tool.build_plan(col, rows), "20260101T000000Z")
    assert second == {"matched": 0, "modified": 0}
