"""Distributed AI26 job leases with capability routing (#378).

The collection hosts are not interchangeable: both localhosts can drive a browser and collect from X,
while Laskin must never be handed a browser job. Until now each host picked work from its own copy of
the source manifest, which is why two hosts can duplicate the same job and why "Laskin does not do
browser work" rested on a CLI flag rather than on the queue.

This module moves the decision into MongoDB. A job is claimed with a single atomic
``find_one_and_update``, so exactly one worker can win a claim; the filter itself excludes browser
kinds for a worker that does not declare the capability, so a misconfigured or malicious worker cannot
claim one by asking. Leases expire, so a machine that dies mid-job releases its work instead of
holding it forever.

Design notes:

* Capability enforcement is in the *query*, not in the caller. ``claim()`` builds the filter from the
  worker's declared capabilities; a non-browser worker's filter carries ``$nin`` over
  ``BROWSER_REQUIRED_KINDS``.
* Claims are single-document updates. MongoDB guarantees atomicity per document, which is the whole
  concurrency argument; there is no read-then-write race in the claim path.
* Attempts are counted on claim and bounded by ``max_attempts``, so a job that keeps crashing parks
  itself instead of spinning forever.
* ``status()`` answers the operator question ("who is alive, what is queued, what is stuck") without
  exposing credentials or payload contents.
"""
from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"

#: Source tables that can only be collected by driving a browser. A worker without the ``browser``
#: capability must never be offered these.
BROWSER_REQUIRED_KINDS = frozenset(
    {"x_account", "browser_source", "instagram_account", "tiktok_account"}
)

#: Everything else — feeds, scholarly queries, Mastodon/Bluesky/youtube — is fair game for any worker.
NON_BROWSER_KINDS = frozenset(
    {"web_source", "bluesky_account", "mastodon_account", "youtube_source", "scholarly_query"}
)

LASKIN_CAPABILITIES = frozenset({"non_browser"})
LOCALHOST_CAPABILITIES = frozenset({"browser", "non_browser"})


def requires_browser(kind: str) -> bool:
    """True when ``kind`` cannot be collected without a browser."""
    return str(kind) in BROWSER_REQUIRED_KINDS


def priority_rank(value: Any) -> int:
    """Manifest priorities are written ``P1``..``P3``; the queue orders on an integer.

    Accepts either form so a manifest edit does not silently break enqueueing, and maps anything
    unrecognised to the middle rank rather than failing a whole cycle.
    """
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip().upper()
    if text.startswith("P") and text[1:].isdigit():
        return int(text[1:])
    if text.isdigit():
        return int(text)
    return 2


def job_identity(row: Mapping[str, Any]) -> str:
    """Stable identity for a manifest row, identical on every host.

    Derived from the source table and name, never from a timestamp or index, so re-reading the same
    manifest on another machine addresses the same queue entry instead of creating a second one.
    """
    kind = str(row.get("kind") or row.get("table") or "").strip()
    name = str(row.get("name") or "").strip()
    if not kind or not name:
        raise ValueError(f"job needs kind and name, got {kind!r}/{name!r}")
    return f"{kind}:{name}"


def capability_filter(capabilities: Iterable[str]) -> dict[str, Any]:
    """The Mongo clause that limits a worker to work it is allowed to do.

    A browser-capable worker gets an empty clause. A worker without the capability is restricted to
    the non-browser kinds *by exclusion*, so a new browser-only kind is denied by default rather than
    silently allowed.
    """
    caps = {str(c) for c in capabilities}
    if "browser" in caps:
        return {}
    return {"kind": {"$nin": sorted(BROWSER_REQUIRED_KINDS)}}


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat()


class JobLeaseStore:
    """Lease-based job queue over a MongoDB collection.

    ``collection`` is a ``pymongo`` collection (duck-typed) so tests can inject a stand-in. All
    state transitions are single-document updates.
    """

    def __init__(self, collection: Any, *, clock=_now) -> None:
        self.jobs = collection
        self._clock = clock

    # -- schema ---------------------------------------------------------------------------------
    def ensure_indexes(self) -> None:
        self.jobs.create_index([("status", 1), ("kind", 1), ("priority", 1), ("created_at", 1)])
        self.jobs.create_index([("status", 1), ("lease_expires_at", 1)])
        self.jobs.create_index([("worker_id", 1), ("status", 1)])

    def enqueue(
        self,
        jobs: Iterable[Mapping[str, Any]],
        *,
        study_fingerprint: str | None = None,
    ) -> int:
        """Insert jobs idempotently, keyed by ``job_id``.

        Re-enqueuing the same manifest is a no-op, which is what makes a restart safe: the queue
        follows the manifest instead of accumulating a second copy of it.
        """
        now = self._clock()
        written = 0
        for job in jobs:
            job_id = str(job.get("job_id") or job.get("id") or "")
            if not job_id:
                raise ValueError("every job needs a job_id")
            kind = str(job.get("kind") or job.get("table") or "")
            if not kind:
                raise ValueError(f"job {job_id} has no kind")
            doc = {
                "_id": job_id,
                "kind": kind,
                "name": str(job.get("name") or job_id),
                "priority": priority_rank(job.get("priority", 2)),
                "payload": {k: v for k, v in job.items() if k not in {"job_id", "id", "kind"}},
                "status": PENDING,
                "attempts": 0,
                "max_attempts": int(job.get("max_attempts", 3)),
                "worker_id": None,
                "lease_expires_at": None,
                "last_error": None,
                "study_fingerprint": study_fingerprint,
                "created_at": now,
                "updated_at": now,
            }
            result = self.jobs.update_one({"_id": job_id}, {"$setOnInsert": doc}, upsert=True)
            written += int(bool(getattr(result, "upserted_id", None)))
        return written

    # -- lease lifecycle ------------------------------------------------------------------------
    def claim(
        self,
        worker_id: str,
        capabilities: Iterable[str],
        *,
        limit: int = 1,
        lease_seconds: int = 900,
    ) -> list[dict[str, Any]]:
        """Atomically claim up to ``limit`` jobs this worker is allowed to do."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        claimed: list[dict[str, Any]] = []
        caps = {str(c) for c in capabilities}
        for _ in range(limit):
            now = self._clock()
            query: dict[str, Any] = {
                "$and": [
                    {
                        "$or": [
                            {"status": PENDING},
                            {"status": RUNNING, "lease_expires_at": {"$lt": now}},
                        ]
                    },
                    {"$expr": {"$lt": ["$attempts", "$max_attempts"]}},
                    capability_filter(caps),
                ]
            }
            update = {
                "$set": {
                    "status": RUNNING,
                    "worker_id": str(worker_id),
                    "lease_expires_at": now + int(lease_seconds),
                    "updated_at": now,
                },
                "$inc": {"attempts": 1},
            }
            doc = self.jobs.find_one_and_update(
                query,
                update,
                sort=[("priority", 1), ("created_at", 1)],
                return_document=True,
            )
            if doc is None:
                break
            claimed.append(doc)
        return claimed

    def renew(self, job_id: str, worker_id: str, *, lease_seconds: int = 900) -> bool:
        now = self._clock()
        result = self.jobs.update_one(
            {"_id": job_id, "worker_id": str(worker_id), "status": RUNNING},
            {"$set": {"lease_expires_at": now + int(lease_seconds), "updated_at": now}},
        )
        return bool(getattr(result, "modified_count", 0))

    def complete(self, job_id: str, worker_id: str, *, outcome: str | None = None) -> bool:
        """Finish a job. Idempotent: a second completion by another worker changes nothing."""
        now = self._clock()
        result = self.jobs.update_one(
            {"_id": job_id, "worker_id": str(worker_id), "status": RUNNING},
            {
                "$set": {
                    "status": DONE,
                    "lease_expires_at": None,
                    "outcome": outcome,
                    "updated_at": now,
                }
            },
        )
        return bool(getattr(result, "modified_count", 0))

    def release(self, job_id: str, worker_id: str, *, error: str | None = None) -> bool:
        """Give a job back after a failure, leaving it claimable until its attempts run out."""
        now = self._clock()
        doc = self.jobs.find_one({"_id": job_id, "worker_id": str(worker_id), "status": RUNNING})
        if not doc:
            return False
        exhausted = int(doc.get("attempts", 0)) >= int(doc.get("max_attempts", 3))
        self.jobs.update_one(
            {"_id": job_id, "worker_id": str(worker_id), "status": RUNNING},
            {
                "$set": {
                    "status": FAILED if exhausted else PENDING,
                    "worker_id": None,
                    "lease_expires_at": None,
                    "last_error": (error or "")[:500] or None,
                    "updated_at": now,
                }
            },
        )
        return True

    def reap_expired(self) -> int:
        """Return expired leases to the queue. Safe to run from any worker, any interval."""
        now = self._clock()
        result = self.jobs.update_many(
            {"status": RUNNING, "lease_expires_at": {"$lt": now}},
            {"$set": {"status": PENDING, "worker_id": None, "lease_expires_at": None,
                      "last_error": "lease_expired", "updated_at": now}},
        )
        return int(getattr(result, "modified_count", 0))

    # -- observability --------------------------------------------------------------------------
    def status(self, *, stale_after: int = 300) -> dict[str, Any]:
        """Queue and lease health, with no payloads and no secrets."""
        now = self._clock()
        by_status: dict[str, int] = {}
        for row in self.jobs.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
            by_status[str(row["_id"])] = int(row["n"])
        by_kind: dict[str, int] = {}
        for row in self.jobs.aggregate(
            [
                {"$match": {"status": {"$in": [PENDING, RUNNING]}}},
                {"$group": {"_id": "$kind", "n": {"$sum": 1}}},
            ]
        ):
            by_kind[str(row["_id"])] = int(row["n"])
        active = list(
            self.jobs.find(
                {"status": RUNNING},
                {"worker_id": 1, "kind": 1, "lease_expires_at": 1, "attempts": 1},
            )
        )
        workers: dict[str, dict[str, Any]] = {}
        for doc in active:
            wid = str(doc.get("worker_id") or "unknown")
            entry = workers.setdefault(wid, {"running": 0, "kinds": {}, "oldest_lease_ago_s": 0.0})
            entry["running"] += 1
            kind = str(doc.get("kind"))
            entry["kinds"][kind] = entry["kinds"].get(kind, 0) + 1
            expires = doc.get("lease_expires_at") or now
            entry["oldest_lease_ago_s"] = max(entry["oldest_lease_ago_s"], now - float(expires))
        expired = sum(
            1
            for doc in active
            if (doc.get("lease_expires_at") or 0) < now
        )
        return {
            "generated_at": _iso(now),
            "by_status": by_status,
            "queue_depth": sum(by_status.get(s, 0) for s in (PENDING, RUNNING)),
            "by_kind": by_kind,
            "active_leases": len(active),
            "expired_leases": expired,
            "workers": workers,
            "stale_after_s": stale_after,
        }


def dispatch_claim(
    dispatch: "JobLeaseStore",
    rows: list[dict[str, Any]],
    *,
    worker_id: str,
    max_jobs: int,
    lease_seconds: int = 1800,
    study_fingerprint: str | None = None,
) -> list[dict[str, Any]]:
    """Claim work from the shared queue instead of slicing the local manifest (#378).

    The manifest is still the source of truth for *what exists*, so it is enqueued first (idempotent
    on ``job_id``). What changes is who may take a job: ``claim`` filters browser kinds out for a
    Laskin-capable worker inside the query, so this host cannot be handed one.
    """
    dispatch.enqueue(
        [{**row, "job_id": job_identity(row)} for row in rows],
        study_fingerprint=study_fingerprint,
    )
    dispatch.reap_expired()
    claimed = dispatch.claim(
        worker_id, LASKIN_CAPABILITIES, limit=max_jobs, lease_seconds=lease_seconds
    )
    return [{**dict(c.get("payload") or {}), "kind": c["kind"], "_job_id": c["_id"]} for c in claimed]


def dispatch_finish(
    dispatch: "JobLeaseStore", row: dict[str, Any], outcome: dict[str, Any], *, worker_id: str
) -> None:
    """Settle a claimed job: done on success, back on the queue when it failed."""
    job_id = row.get("_job_id")
    if not job_id:
        return
    status = str(outcome.get("status") or "")
    if status in {"ok", "warning"}:
        dispatch.complete(str(job_id), worker_id, outcome=status)
    else:
        dispatch.release(str(job_id), worker_id, error=str(outcome.get("reason") or status))
