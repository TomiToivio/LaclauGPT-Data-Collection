"""The capture backend's /status must distinguish "capturing" from "reaching the shared plane".

On 2026-10-28 this host served 146 captures and 0 records reached MongoDB: every raw-envelope PUT was
refused by the CSC Allas quota, and `/status` reported `health: ok` throughout because none of its
counters describe the mirror. `distributed_status()` is the field that makes the difference visible.
"""
from __future__ import annotations

from laclaugpt_data_collection.capture_server import distributed_status, status_payload


class _Mirror:
    synced_total = 12
    rejected_total = 2
    last_error = "ObjectStoreError upload failed for projects/ai26/runs/r/raw/x.json: QuotaExceeded"


class _Store:
    def seen_count(self) -> int:
        return 9642


class _Config:
    study = "ai26"


class _Server:
    run_id = "20261028T171540Z"
    capture_media_inline = False
    capture_media_max_bytes = 67108864
    stats = {"captures": 146, "posts": 7, "errors": 43}

    def __init__(self, mirror=None) -> None:
        self.store = _Store()
        self.cfg = _Config()
        self.mirror = mirror

    def active(self) -> bool:
        return True

    def local_today(self):
        return "2026-10-28"


def test_local_only_profile_says_so_instead_of_looking_healthy() -> None:
    assert distributed_status(None)["enabled"] is False
    assert "local-only" in distributed_status(None)["reason"]


def test_a_failing_mirror_reports_its_error() -> None:
    payload = distributed_status(_Mirror())
    assert payload["enabled"] is True
    assert payload["synced_total"] == 12
    assert payload["rejected_total"] == 2
    assert "QuotaExceeded" in payload["last_error"]
    assert len(payload["last_error"]) <= 300


def test_status_payload_carries_the_capture_counters_and_the_mirror() -> None:
    payload = status_payload(_Server(_Mirror()))
    assert payload["study"] == "ai26"
    assert payload["stats"]["captures"] == 146
    assert payload["seen_total"] == 9642
    assert payload["distributed"]["enabled"] is True
    assert "QuotaExceeded" in payload["distributed"]["last_error"]


def test_status_payload_works_for_a_server_without_a_mirror_attribute() -> None:
    """The attribute is set by run_backend; a server built directly must not raise."""
    server = _Server()
    del server.mirror
    payload = status_payload(server)
    assert payload["distributed"]["enabled"] is False


def test_a_quota_failure_during_the_startup_replay_must_not_stop_the_backend() -> None:
    """The replay is an optimisation; the capture path is the product.

    Measured 2026-10-28: the first replayed record raised ``ObjectStoreError`` and the unguarded
    call exited the backend, so the Firefox extension had nothing to post to.
    """
    from laclaugpt_data_collection.ai26_browser import startup_scan

    class _Raising:
        last_error = ""
        calls = 0

        def scan_once(self):
            self.calls += 1
            raise RuntimeError("upload failed: QuotaExceeded")

    mirror = _Raising()
    assert startup_scan(mirror) is False
    assert mirror.calls == 1
    assert "QuotaExceeded" in mirror.last_error


def test_a_successful_startup_replay_is_reported_as_such() -> None:
    from laclaugpt_data_collection.ai26_browser import startup_scan

    class _Fine:
        last_error = ""

        def scan_once(self):
            return {"scanned": 1, "synced": 1, "rejected": 0}

    assert startup_scan(_Fine()) is True
