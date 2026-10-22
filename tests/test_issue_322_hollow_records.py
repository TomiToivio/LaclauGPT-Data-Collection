"""Issue #322: a hollow canonical row must never reach the shared store.

On 2026-10-22 10:53 UTC the mirror replayed local canonical rows that carried a real
X URL and nothing else — no text, no payload, no publication time, no platform, no
author. 1 703 of them entered `ai26__records`, doubling every denominator that did
not filter on `handoff.status`, and none of them can be repaired because the text
was never persisted.

The guard is a refusal, not a repair: the sink raises ``HollowRecordError`` before
any write, and the mirror counts what it refused and moves on. These tests pin the
predicate, the refusal, and the mirror's behaviour on a mixed file.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from laclaugpt_data_collection.ai26_browser import JsonlDistributedMirror
from laclaugpt_data_collection.distributed_capture import (
    DistributedCaptureSink,
    HollowRecordError,
    is_hollow,
)
from laclaugpt_data_collection.models import CanonicalRecord


def _Settings() -> SimpleNamespace:  # noqa: N802 - a stand-in for Settings
    return SimpleNamespace(project_id="ai26", run_id="run", machine="m", execution="e")


def _record(**overrides) -> CanonicalRecord:
    defaults = {
        "source_url": "https://x.com/OpenAI/status/1",
        "source": {"platform": "x", "created_at": "2026-10-20T09:00:00Z"},
        "content": {"text": "a real post"},
        "raw_capture": {"payload": {"rest_id": "1"}},
    }
    defaults.update(overrides)
    return CanonicalRecord.model_validate(defaults)


# ------------------------------------------------------------------- predicate
def test_a_url_with_nothing_else_is_hollow() -> None:
    assert is_hollow(CanonicalRecord(source_url="https://x.com/OpenAI/status/1")) is True


def test_whitespace_text_counts_as_no_text() -> None:
    hollow = _record(content={"text": "   \n\t"}, raw_capture={"payload": None}, source={"platform": "", "created_at": None})
    assert is_hollow(hollow) is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"content": {"text": "a real post"}, "raw_capture": {"payload": None}, "source": {"created_at": None}},
        {"content": {"text": ""}, "raw_capture": {"payload": {"rest_id": "1"}}, "source": {"created_at": None}},
        {"content": {"text": ""}, "raw_capture": {"payload": None}, "source": {"created_at": "2026-10-20T09:00:00Z"}},
    ],
)
def test_any_one_of_text_payload_or_time_is_enough(overrides: dict) -> None:
    assert is_hollow(_record(**overrides)) is False


# --------------------------------------------------------------------- refusal
def test_the_sink_refuses_before_it_touches_a_store() -> None:
    sink = DistributedCaptureSink.__new__(DistributedCaptureSink)
    sink.settings = _Settings()  # type: ignore[assignment]  # no store is constructed

    with pytest.raises(HollowRecordError) as excinfo:
        sink.ingest_with_status({"source_url": "https://x.com/OpenAI/status/1"})

    assert excinfo.value.reason == "hollow_record"
    assert "no content.text" in str(excinfo.value)
    assert "https://x.com/OpenAI/status/1" in str(excinfo.value)


def test_a_complete_record_still_passes_the_predicate() -> None:
    assert is_hollow(_record()) is False


# ---------------------------------------------------------------------- mirror
class _Sink:
    """A sink that behaves like the real one: hollow rows are refused."""

    def __init__(self) -> None:
        self.stored: list[str] = []

    def ingest(self, record: dict) -> None:
        if is_hollow(CanonicalRecord.model_validate(
            {k: v for k, v in record.items() if k in CanonicalRecord.model_fields}
            | {"source_url": record["source_url"]}
        )):
            raise HollowRecordError(f"hollow {record['source_url']}")
        self.stored.append(record["source_url"])


def _mirror(tmp_path: Path, sink: _Sink) -> JsonlDistributedMirror:
    mirror = JsonlDistributedMirror.__new__(JsonlDistributedMirror)
    mirror.data_root = tmp_path
    mirror.normalized_dir = tmp_path / "normalized"
    mirror.normalized_dir.mkdir(parents=True, exist_ok=True)
    mirror.state_path = tmp_path / ".ai26-distributed-offsets.json"
    mirror.sink = sink  # type: ignore[assignment]  # the real sink needs Mongo and S3
    mirror._offsets = {}
    mirror.synced_total = 0
    mirror.hollow_refused = 0
    return mirror


def test_the_mirror_skips_hollow_rows_counts_them_and_keeps_going(tmp_path: Path) -> None:
    rows = [
        {"source_url": "https://x.com/OpenAI/status/1", "collection_id": "ai26"},
        {"source_url": "https://x.com/OpenAI/status/2", "collection_id": "ai26",
         "source": {"platform": "x", "created_at": "2026-10-20T09:00:00Z"},
         "content": {"text": "real"}, "raw_capture": {"payload": {"rest_id": "2"}}},
        {"source_url": "https://x.com/OpenAI/status/3", "collection_id": "ai26"},
    ]
    sink = _Sink()
    mirror = _mirror(tmp_path, sink)
    (tmp_path / "normalized" / "x.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    result = mirror.scan_once()

    assert result == {"scanned": 3, "synced": 1, "hollow": 2}
    assert sink.stored == ["https://x.com/OpenAI/status/2"]
    assert mirror.hollow_refused == 2
    # The offsets advance past the refused rows, so the next scan does not re-read
    # them forever: a refusal is final, not a retry loop.
    assert mirror._offsets["x.jsonl"] == (tmp_path / "normalized" / "x.jsonl").stat().st_size


def test_a_second_scan_of_a_refused_file_writes_nothing(tmp_path: Path) -> None:
    sink = _Sink()
    mirror = _mirror(tmp_path, sink)
    (tmp_path / "normalized" / "x.jsonl").write_text(
        json.dumps({"source_url": "https://x.com/OpenAI/status/1", "collection_id": "ai26"}) + "\n",
        encoding="utf-8",
    )
    mirror.scan_once()

    again = mirror.scan_once()

    assert again == {"scanned": 0, "synced": 0, "hollow": 0}
    assert sink.stored == []
