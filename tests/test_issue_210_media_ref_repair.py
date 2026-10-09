# -*- coding: utf-8 -*-
"""Issue #210 — completed media must not be lost to a re-ingest, and must self-repair.

Two defects compounded into a self-sealing deadlock: 97 arxiv records (12.3% of
the store) were pinned in ``handoff.status: waiting_media`` because their
``object_ref`` was empty while the durable media index already said
``completed``. The media worker's own idempotency guard skips terminal rows, so
nothing in the scheduled path could ever clear it.

- **Cause 1** — ``upsert`` is a full-document replace, so a later re-ingest of a
  record whose media was already downloaded writes ``object_ref: ""`` back.
  Fixed by carrying resolved refs forward on every write.
- **Cause 2** — the downloader skips a ref whose media index row is terminal, so
  an already-lost ref is never revisited. Fixed by repairing from the durable
  index before the enqueue.

These tests pin both halves. They are pure-function tests: no Mongo, no S3, no
network. The live repair of the existing backlog is an operational step, not a
test concern.
"""
from __future__ import annotations

from pathlib import Path

from laclaugpt_data_collection.distributed_media_runner import (
    repair_media_references,
)
from laclaugpt_data_collection.storage.remote import _carry_forward_media_state


def _ref(url: str, media_index: int = 0, object_ref: str = "", checksum: str = "") -> dict:
    return {
        "url": url,
        "media_index": media_index,
        "object_ref": object_ref,
        "checksum": checksum,
        "metadata": {},
    }


def _record(url: str, refs: list[dict], *, collection: str = "ai26") -> dict:
    return {
        "source_url": url,
        "collection_id": collection,
        "content": {"media_references": refs},
        "provenance": [{"metadata": {"collection_id": collection}}],
    }


def _state(
    media_index: int,
    url: str,
    *,
    status: str = "completed",
    local_path: str = "s3://bucket/media/x.pdf",
    sha256: str = "abc123",
) -> dict:
    return {
        "media_key": f"ai26:arxiv:deadbeef:{media_index}",
        "media_index": media_index,
        "url": url,
        "local_path": local_path,
        "sha256": sha256,
        "status": status,
        "byte_size": 1234,
        "mime_type": "application/pdf",
    }


class TestRepairFromDurableIndex:
    """Cause 2: an empty ref whose media is terminal must be repaired."""

    def test_completed_media_with_lost_ref_is_restored(self) -> None:
        url = "https://arxiv.org/abs/2610.02207v1"
        record = _record(url, [_ref(url, object_ref="")])
        states = {url: [_state(0, url)]}

        touched = repair_media_references([record], states, default_collection="ai26")

        assert len(touched) == 1, "the record with a lost pointer must be repaired"
        ref = touched[0]["content"]["media_references"][0]
        assert ref["object_ref"] == "s3://bucket/media/x.pdf"
        assert ref["checksum"] == "abc123"
        assert ref["metadata"]["download_status"] == "completed"
        assert ref["metadata"]["repaired_from_media_index"] is True

    def test_a_ref_that_already_has_an_object_ref_is_left_alone(self) -> None:
        url = "https://arxiv.org/abs/2610.02207v1"
        record = _record(url, [_ref(url, object_ref="s3://already/there.pdf")])
        states = {url: [_state(0, url, local_path="s3://different.pdf")]}

        touched = repair_media_references([record], states, default_collection="ai26")

        assert touched == [], "nothing to repair when the pointer is present"
        assert record["content"]["media_references"][0]["object_ref"] == "s3://already/there.pdf"

    def test_non_terminal_media_is_not_repaired(self) -> None:
        """A genuinely unfinished download must stay for the downloader."""
        url = "https://arxiv.org/abs/2610.02207v1"
        record = _record(url, [_ref(url, object_ref="")])
        states = {url: [_state(0, url, status="pending", local_path="")]}

        touched = repair_media_references([record], states, default_collection="ai26")

        assert touched == [], "a pending download is not a repair candidate"

    def test_a_mismatched_url_is_not_repaired_across_a_shifted_index(self) -> None:
        """The index must match the ref, so a shifted position cannot attach the wrong object."""
        url = "https://arxiv.org/abs/2610.02207v1"
        other = "https://arxiv.org/abs/2610.99999v1"
        record = _record(url, [_ref(url, object_ref="")])
        states = {url: [_state(0, other)]}  # index 0 belongs to a DIFFERENT url

        touched = repair_media_references([record], states, default_collection="ai26")

        assert touched == [], "a url mismatch must never attach the wrong object"

    def test_repair_is_idempotent(self) -> None:
        url = "https://arxiv.org/abs/2610.02207v1"
        record = _record(url, [_ref(url, object_ref="")])
        states = {url: [_state(0, url)]}
        repair_media_references([record], states, default_collection="ai26")
        touched_again = repair_media_references([record], states, default_collection="ai26")
        assert touched_again == [], "the second pass has nothing left to do"


class TestCarryForwardOnUpsert:
    """Cause 1: the wipe must be stopped at the write, not repaired after it."""

    def test_resolved_ref_survives_a_re_ingest(self) -> None:
        url = "https://arxiv.org/abs/2610.02207v1"
        stored = _record(url, [_ref(url, object_ref="s3://media/x.pdf", checksum="abc")])
        stored["content"]["media_references"][0]["metadata"] = {
            "download_status": "completed",
            "mime_type": "application/pdf",
        }
        incoming = _record(url, [_ref(url, object_ref="")])  # a fresh re-ingest

        _carry_forward_media_state(incoming, stored)

        ref = incoming["content"]["media_references"][0]
        assert ref["object_ref"] == "s3://media/x.pdf", "the pointer must survive the replace"
        assert ref["checksum"] == "abc"
        assert ref["metadata"]["carried_forward_from_prior_ingest"] is True

    def test_a_new_ref_the_stored_document_lacks_is_untouched(self) -> None:
        url = "https://arxiv.org/abs/2610.02207v1"
        stored = _record(url, [_ref(url, object_ref="s3://media/x.pdf")])
        incoming = _record(url, [_ref(url, object_ref="")])  # same url, no prior match needed
        incoming["content"]["media_references"].append(
            _ref("https://arxiv.org/abs/2610.00001v1", media_index=1, object_ref="")
        )

        _carry_forward_media_state(incoming, stored)

        assert incoming["content"]["media_references"][0]["object_ref"] == "s3://media/x.pdf"
        assert incoming["content"]["media_references"][1]["object_ref"] == "", (
            "a ref with no stored counterpart must stay empty for the downloader"
        )

    def test_a_genuinely_empty_stored_ref_is_not_carried(self) -> None:
        url = "https://arxiv.org/abs/2610.02207v1"
        stored = _record(url, [_ref(url, object_ref="")])  # nothing resolved yet
        incoming = _record(url, [_ref(url, object_ref="")])

        _carry_forward_media_state(incoming, stored)

        assert incoming["content"]["media_references"][0]["object_ref"] == ""


class TestRunnerWiresBothHalves:
    """The repair must run BEFORE the enqueue, or the terminal-row skip defeats it."""

    def test_distributed_runner_repairs_before_enqueue(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "laclaugpt_data_collection"
            / "distributed_media_runner.py"
        ).read_text(encoding="utf-8")
        # Scope to the DISTRIBUTED path: the local path legitimately has no repair
        # (no durable remote media). Slicing from the distributed function avoids
        # matching the local path's enqueue call.
        distributed = source[source.index("def _run_distributed_media_unlocked("):]
        repair_at = distributed.index("repaired = repair_media_references(")
        enqueue_at = distributed.index("jobs = downloader.enqueue_from_records(records)")
        assert repair_at < enqueue_at, (
            "repair_media_references must be called before enqueue_from_records: "
            "the downloader skips terminal media rows by design (#210)"
        )
        assert '"media_refs_repaired"' in distributed, "the run must report the repaired count"
