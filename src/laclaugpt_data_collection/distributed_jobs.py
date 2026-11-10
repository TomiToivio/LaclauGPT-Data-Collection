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
  worker's declared capabilities; a non-browser worker uses an explicit allowlist
  of ``NON_BROWSER_KINDS``.
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
#: A job whose manifest row was deactivated. Kept, not deleted: the queue has to remember that it
#: used to exist, or the next re-read of the manifest resurrects it.
CANCELLED = "cancelled"

#: A manifest row describes a source that is *polled*, not a task that runs once (#400). One hour is
#: the collector's own cycle, so the default reproduces the pre-#378 behaviour in which every
#: active row was collected every cycle. A row may override it with ``poll_minutes``.
DEFAULT_POLL_SECONDS = 3600

#: Manifest keys that may carry a per-row cadence, in order of precedence.
POLL_KEYS = ("poll_minutes", "cadence_minutes", "interval_minutes")


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


def poll_seconds_for(row: Mapping[str, Any]) -> int:
    """How often a manifest row should be collected again, in seconds (#400).

    A row may say ``poll_minutes`` (preferred), ``cadence_minutes`` or ``interval_minutes``. Zero
    means "never again" and is a deliberate choice a manifest can make; the default is the
    collector's own cycle, which is what every active row effectively had before the shared queue
    turned each of them into a one-shot job.
    """
    for key in POLL_KEYS:
        if key in row and row[key] not in (None, ""):
            try:
                minutes = float(row[key])
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be a number, got {row[key]!r}") from None
            if minutes < 0:
                raise ValueError(f"{key} must not be negative, got {minutes}")
            return int(minutes * 60)
    if row.get("poll_seconds") is not None:
        seconds = int(row["poll_seconds"])
        if seconds < 0:
            raise ValueError("poll_seconds must not be negative")
        return seconds
    return DEFAULT_POLL_SECONDS


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
    explicitly classified non-browser kinds *by inclusion*, so unknown kinds are denied
    by default.
    """
    caps = {str(c) for c in capabilities}
    if "browser" in caps:
        return {}
    return {"kind": {"$in": sorted(NON_BROWSER_KINDS)}}


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

        Re-enqueuing the same manifest is a no-op for the *state* of an existing job, which is what
        makes a restart safe. What is not frozen is the definition: payload, priority and poll
        cadence follow the manifest, so an edited row takes effect without a migration (#400).
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
            payload = {k: v for k, v in job.items() if k not in {"job_id", "id", "kind"}}
            priority = priority_rank(job.get("priority", 2))
            poll_seconds = poll_seconds_for(job)
            max_attempts = int(job.get("max_attempts", 3))
            result = self.jobs.update_one(
                {"_id": job_id},
                {
                    # State and identity: written once, never overwritten by a manifest re-read.
                    "$setOnInsert": {
                        "_id": job_id,
                        "status": PENDING,
                        "attempts": 0,
                        "worker_id": None,
                        "lease_expires_at": None,
                        "last_error": None,
                        "study_fingerprint": study_fingerprint,
                        "created_at": now,
                        "next_run_at": now,
                    },
                    # Definition: follows the manifest, so an edited row takes effect. The next run
                    # time is *not* here: re-reading the manifest must not reset a finished job's
                    # schedule, or every cycle would re-run every source regardless of cadence.
                    "$set": {
                        "name": str(job.get("name") or job_id),
                        "kind": kind,
                        "priority": priority,
                        "payload": payload,
                        "poll_seconds": poll_seconds,
                        "max_attempts": max_attempts,
                        "updated_at": now,
                    },
                },
                upsert=True,
            )
            written += int(bool(getattr(result, "upserted_id", None)))
        return written

    def cancel_missing(self, active_ids: Iterable[str]) -> int:
        """Retire queue entries whose manifest row is gone or ``active = false`` (#400).

        The six deactivated ``scholarly_query`` rows kept being claimed for two hours after the
        manifest said they were off, because nothing in the queue knew about the manifest. A
        cancelled job stays in the collection as evidence of what used to be configured.
        """
        keep = [str(j) for j in active_ids]
        now = self._clock()
        result = self.jobs.update_many(
            {"_id": {"$nin": keep}, "status": {"$in": [PENDING, RUNNING, DONE, FAILED]}},
            {"$set": {"status": CANCELLED, "worker_id": None, "lease_expires_at": None,
                      "updated_at": now}},
        )
        return int(getattr(result, "modified_count", 0))

    def rearm_due(self) -> int:
        """Turn finished recurring jobs back into work whose cadence has elapsed (#400).

        This is the whole fix for the drained queue: completion is a *state*, not an ending. A job
        with ``poll_seconds > 0`` becomes pending again when its next run is due, with a fresh
        attempt budget — otherwise one transient failure would end a source for the rest of the
        study. Cancelled jobs are deliberately excluded: deactivation must survive.
        """
        now = self._clock()
        result = self.jobs.update_many(
            {
                "poll_seconds": {"$gt": 0},
                "status": {"$in": [DONE, FAILED]},
                # A job that finished before ``next_run_at`` existed has no schedule to compare
                # against. Treat it as due once: it runs, and from then on it has a real one. The
                # alternative — waiting for a field that nothing will ever write — is exactly the
                # drained queue this issue is about, wearing a migration.
                "$or": [{"next_run_at": {"$lte": now}},
                        {"next_run_at": {"$exists": False}}],
            },
            {"$set": {"status": PENDING, "attempts": 0, "worker_id": None,
                      "lease_expires_at": None, "last_error": None, "updated_at": now}},
        )
        return int(getattr(result, "modified_count", 0))


    # -- lease lifecycle ------------------------------------------------------------------------
    def claim(
        self,
        worker_id: str,
        capabilities: Iterable[str],
        *,
        limit: int = 1,
        lease_seconds: int = 900,
        kinds: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Atomically claim up to ``limit`` jobs this worker is allowed to do."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        allowed_kinds = sorted({str(k) for k in kinds}) if kinds is not None else None
        if allowed_kinds is not None and not allowed_kinds:
            return []
        claimed: list[dict[str, Any]] = []
        caps = {str(c) for c in capabilities}
        for _ in range(limit):
            now = self._clock()
            query: dict[str, Any] = {
                "$and": [
                    {
                        "$or": [
                            {"status": PENDING, "$or": [
                                {"next_run_at": {"$lte": now}},
                                {"next_run_at": {"$exists": False}},
                            ]},
                            {"status": RUNNING, "lease_expires_at": {"$lt": now}},
                        ]
                    },
                    {"$expr": {"$lt": ["$attempts", "$max_attempts"]}},
                    capability_filter(caps),
                    *([{"kind": {"$in": allowed_kinds}}] if allowed_kinds is not None else []),
                ]
            }
            update = {
                "$set": {
                    "status": RUNNING,
                    "worker_id": str(worker_id),
                    "lease_expires_at": now + int(lease_seconds),
                    "updated_at": now,
                    "last_claimed_at": now,
                },
                "$inc": {"attempts": 1},
            }
            doc = self.jobs.find_one_and_update(
                query,
                update,
                # Rotate equally prioritised sources by the last actual claim.
                # Older never-claimed jobs sort first (Mongo null/missing first).
                # The stable _id tail makes the result independent of query plan.
                sort=[("priority", 1), ("last_claimed_at", 1), ("_id", 1)],
                return_document=True,
            )
            if doc is None:
                break
            claimed.append(doc)
        return claimed

    def claimable_count(
        self, capabilities: Iterable[str], *, kinds: Iterable[str] | None = None
    ) -> int:
        """Eligible, due jobs not yet claimed, for cycle backlog visibility (#406)."""
        now = self._clock()
        clauses: list[dict[str, Any]] = [
            {"$or": [
                {"status": PENDING, "$or": [
                    {"next_run_at": {"$lte": now}},
                    {"next_run_at": {"$exists": False}},
                ]},
                {"status": RUNNING, "lease_expires_at": {"$lt": now}},
            ]},
            {"$expr": {"$lt": ["$attempts", "$max_attempts"]}},
            capability_filter(capabilities),
        ]
        if kinds is not None:
            allowed = sorted({str(k) for k in kinds})
            if not allowed:
                return 0
            clauses.append({"kind": {"$in": allowed}})
        return int(self.jobs.count_documents({"$and": clauses}))

    def renew(self, job_id: str, worker_id: str, *, lease_seconds: int = 900) -> bool:
        now = self._clock()
        result = self.jobs.update_one(
            {"_id": job_id, "worker_id": str(worker_id), "status": RUNNING},
            {"$set": {"lease_expires_at": now + int(lease_seconds), "updated_at": now}},
        )
        return bool(getattr(result, "modified_count", 0))

    def complete(self, job_id: str, worker_id: str, *, outcome: str | None = None) -> bool:
        """Finish a job. Idempotent: a second completion by another worker changes nothing.

        Completing a *recurring* job also schedules its next run (#400). Completion is a state, not
        an ending: without this line every manifest row ran exactly once per study and the queue
        drained to zero while the collector kept reporting ``ok``.
        """
        now = self._clock()
        doc = self.jobs.find_one({"_id": job_id, "worker_id": str(worker_id), "status": RUNNING})
        if not doc:
            return False
        update: dict[str, Any] = {
            "status": DONE,
            "lease_expires_at": None,
            "outcome": outcome,
            "updated_at": now,
        }
        poll = int(doc.get("poll_seconds", 0) or 0)
        if poll > 0:
            update["next_run_at"] = now + poll
        result = self.jobs.update_one(
            {"_id": job_id, "worker_id": str(worker_id), "status": RUNNING},
            {"$set": update},
        )
        return bool(getattr(result, "modified_count", 0))

    def release(
        self,
        job_id: str,
        worker_id: str,
        *,
        error: str | None = None,
        refund_attempt: bool = False,
    ) -> bool:
        """Give a job back after a failure, leaving it claimable until its attempts run out.

        ``refund_attempt`` exists for failures that say nothing about the *job*: an object
        store that is out of quota, a database that is unreachable. Those must not consume
        the retry budget, or a single infrastructure outage permanently drains the queue —
        which is exactly what happened on 2026-10-28, when an exhausted Allas quota burned
        three attempts off every job in one hour.
        """
        now = self._clock()
        doc = self.jobs.find_one({"_id": job_id, "worker_id": str(worker_id), "status": RUNNING})
        if not doc:
            return False
        if refund_attempt:
            self.jobs.update_one({"_id": job_id}, {"$inc": {"attempts": -1}})
            doc["attempts"] = max(0, int(doc.get("attempts", 0)) - 1)
        exhausted = int(doc.get("attempts", 0)) >= int(doc.get("max_attempts", 3))
        update: dict[str, Any] = {
            "status": FAILED if exhausted else PENDING,
            "worker_id": None,
            "lease_expires_at": None,
            "last_error": (error or "")[:500] or None,
            "updated_at": now,
        }
        poll = int(doc.get("poll_seconds", 0) or 0)
        if poll > 0:
            # A recurring source does not retry on the next tick just because it failed once; it
            # waits for its cadence, then the next cycle makes it claimable again (#400).
            update["next_run_at"] = now + poll
        self.jobs.update_one(
            {"_id": job_id, "worker_id": str(worker_id), "status": RUNNING},
            {"$set": update},
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
    capabilities: Iterable[str] | None = None,
    executable_kinds: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Claim work from the shared queue instead of slicing the local manifest (#378).

    The manifest is still the source of truth for *what exists*, so it is enqueued first (idempotent
    on ``job_id``). What changes is who may take a job: ``claim`` filters browser kinds out for a
    Laskin-capable worker inside the query, so this host cannot be handed one.
    """
    dispatch.enqueue(
        [{**row, "job_id": job_identity(row)} for row in rows if row.get("active", True) is not False],
        study_fingerprint=study_fingerprint,
    )
    # #400: the manifest also says what *stops* existing. Deactivated rows must not leave a
    # claimable queue entry behind, and finished recurring jobs must become claimable again when
    # their cadence elapses — otherwise the queue drains once and reports `ok` forever.
    # Duck-typed dispatchers (test doubles, older adapters) may not implement these yet.
    cancel_missing = getattr(dispatch, "cancel_missing", None)
    if callable(cancel_missing):
        cancel_missing(job_identity(row) for row in rows if row.get("active", True) is not False)
    rearm_due = getattr(dispatch, "rearm_due", None)
    if callable(rearm_due):
        rearm_due()
    dispatch.reap_expired()
    # #378: the caller declares its capabilities. Defaulting to the Laskin set keeps the
    # original call site honest (a worker that says nothing gets the most restrictive role),
    # while a localhost can pass LOCALHOST_CAPABILITIES and actually receive browser work.
    caps = frozenset(capabilities) if capabilities is not None else LASKIN_CAPABILITIES
    claimed = dispatch.claim(worker_id, caps, limit=max_jobs, lease_seconds=lease_seconds, kinds=executable_kinds)
    return [{**dict(c.get("payload") or {}), "kind": c["kind"], "_job_id": c["_id"]} for c in claimed]


def queue_snapshot(
    docs: Iterable[Mapping[str, Any]], capabilities: Iterable[str]
) -> dict[str, Any]:
    """Summarise the queue for one worker without touching MongoDB.

    Kept pure so the health/status output can be tested with plain dicts. ``browser_backlog``
    is the number of queued browser jobs no non-browser worker may take; surfacing it is the
    point — otherwise a localhost looks idle while X work waits for a human session.
    """
    caps = {str(c) for c in capabilities}
    browser_allowed = "browser" in caps
    by_status: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    browser_backlog = 0
    eligible_pending = 0
    for doc in docs:
        status = str(doc.get("status") or "")
        kind = str(doc.get("kind") or "")
        if status:
            by_status[status] = by_status.get(status, 0) + 1
        if kind:
            by_kind[kind] = by_kind.get(kind, 0) + 1
        browser_kind = requires_browser(kind)
        if browser_kind and status in {PENDING, RUNNING}:
            browser_backlog += 1
        if status == PENDING and (browser_allowed or not browser_kind):
            eligible_pending += 1
    return {
        "capabilities": sorted(caps),
        "by_status": dict(sorted(by_status.items())),
        "by_kind": dict(sorted(by_kind.items())),
        "eligible_pending": eligible_pending,
        "browser_backlog": browser_backlog,
        "browser_capable": browser_allowed,
    }


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
        # An infrastructure failure is not evidence about this job, so it must not spend
        # the job's retry budget.
        dispatch.release(
            str(job_id),
            worker_id,
            error=str(outcome.get("reason") or status),
            refund_attempt=bool(outcome.get("infrastructure")),
        )
