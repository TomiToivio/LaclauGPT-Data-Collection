"""#295 backfill: repair records whose publication time was stored as null.

The parser fixed collection; nine rows were already in the store with
``handoff.published_at = null`` and ``handoff.status = excluded``. The tool's
contract, pinned here:

* it repairs only what the source itself dates -- an undated record stays excluded
  rather than being given an invented time;
* the repaired envelope is the collector's own ``build_handoff`` output, so status
  and reason are the ones collection would have produced;
* it is idempotent without a marker: after repair the field it keys on is set.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "backfill_ai26_publication_time.py"


def _tool():
    spec = importlib.util.spec_from_file_location("backfill_ai26_publication_time", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _doc(
    created_at: str,
    *,
    published_at: str | None = None,
    status: str = "excluded",
    reason: str = "source_publication_time_missing",
    source_name: str = "etui",
    has_handoff: bool = True,
) -> dict:
    record = {
        "project_id": "ai26",
        "collection_id": "ai26",
        "arena": "elites",
        "source_url": "https://www.etui.org/news/example",
        "source": {
            "platform": "rss",
            "created_at": created_at,
            "raw_metadata": {
                "source_name": source_name,
                "collection_id": "ai26",
                "arena": "elites",
            },
        },
        "content": {"text": "ETUI example", "title": "ETUI example"},
        "provenance": [{"metadata": {"collection_id": "ai26", "arena": "elites"}}],
    }
    if has_handoff:
        record["handoff"] = {
            "published_at": published_at,
            "status": status,
            "reason": reason,
        }
    return record


class TestNeedsRepair:
    def test_an_etui_stamp_that_never_parsed_is_repairable(self) -> None:
        tool = _tool()
        assert tool.needs_repair(_doc("Thu, 10/08/2026 - 13:30")) is True

    def test_a_record_without_a_source_date_is_left_alone(self) -> None:
        tool = _tool()
        assert tool.needs_repair(_doc("")) is False

    def test_a_record_that_already_has_a_publication_time_is_left_alone(self) -> None:
        tool = _tool()
        doc = _doc("Thu, 10/08/2026 - 13:30", published_at="2026-10-08T13:30:00+00:00")
        assert tool.needs_repair(doc) is False

    def test_a_document_with_no_handoff_at_all_is_repairable(self) -> None:
        tool = _tool()
        assert tool.needs_repair(_doc("2026-10-08T13:30:00Z", has_handoff=False)) is True


class TestRepair:
    def test_the_repaired_handoff_matches_what_collection_would_produce(self) -> None:
        tool = _tool()
        doc = _doc("Thu, 10/08/2026 - 13:30")
        fields = tool.repair(doc)
        assert fields is not None
        handoff = fields["handoff"]
        assert handoff["published_at"] == "2026-10-08T13:30:00+00:00"
        assert handoff["status"] == "ready"
        assert handoff["reason"] == "source_ready"
        assert handoff["collection_id"] == "ai26"
        assert handoff["handoff_key"]

    def test_the_repair_is_traceable_and_keeps_the_old_value(self) -> None:
        tool = _tool()
        fields = tool.repair(_doc("Thu, 10/08/2026 - 13:30"))
        assert fields is not None
        assert fields["source.backfill"] == "#295"
        assert fields["source.raw_metadata.published_at_repaired"] is True
        assert fields["source.raw_metadata.published_at_before"] == ""

    def test_an_undated_record_gets_no_fields(self) -> None:
        tool = _tool()
        assert tool.repair(_doc("")) is None

    def test_after_repair_nothing_is_left_to_do(self) -> None:
        """Idempotence without a marker: the keyed field is now set."""
        tool = _tool()
        doc = _doc("Thu, 10/08/2026 - 13:30")
        fields = tool.repair(doc)
        assert fields is not None
        doc["handoff"] = fields["handoff"]
        assert tool.needs_repair(doc) is False
        assert tool.repair(doc) is None


class TestSummary:
    def test_it_counts_by_source_and_status_transition(self) -> None:
        tool = _tool()
        documents = [
            _doc("Thu, 10/08/2026 - 13:30"),
            _doc("Wed, 10/07/2026 - 10:00"),
            _doc("", source_name="finland_government"),
            _doc("Thu, 10/15/2026 - 12:00", published_at="2026-10-15T12:00:00+00:00"),
        ]
        report = tool.summary(documents)
        assert report["scanned"] == 4
        assert report["repairable"] == 2
        assert report["by_source"] == {"etui": 2}
        assert report["status_changes"] == {"excluded -> ready": 2}

    def test_a_ready_record_without_a_date_is_not_counted_as_repairable(self) -> None:
        tool = _tool()
        report = tool.summary([_doc("", status="ready", reason="source_ready")])
        assert report["repairable"] == 0
