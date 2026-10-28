#!/usr/bin/env python3
"""End-to-end smoke test of the AI26 job queue against the real MongoDB plane (#378).

Everything happens in a throwaway database (``laclaugpt_smoke_<uuid>``) which is dropped at the end,
so this touches no live collection. It proves, on the machine it runs on, that:

1. the shared MongoDB is reachable with the host's settings;
2. a Laskin-capable worker cannot claim a browser job, even when browser jobs are queued first;
3. a browser-capable worker can claim them;
4. two workers never get the same job;
5. an expired lease is reaped and becomes claimable again;
6. completion is idempotent.

Run on any host: ``python scripts/ai26_jobs_smoke.py --settings <env file>``.
"""
from __future__ import annotations

import argparse
import uuid
from typing import Any

from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.distributed_jobs import (
    BROWSER_REQUIRED_KINDS,
    LASKIN_CAPABILITIES,
    LOCALHOST_CAPABILITIES,
    JobLeaseStore,
)


def load_env_file(path: str) -> None:
    import os
    from pathlib import Path

    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip().removeprefix("export ").strip(), value.strip().strip("'\""))


class MutableClock:
    def __init__(self) -> None:
        self.offset = 0.0

    def __call__(self) -> float:
        import time

        return time.time() + self.offset


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--settings", required=True, help="env file holding the MongoDB settings")
    args = ap.parse_args(argv)
    load_env_file(args.settings)

    settings = Settings()
    if not settings.mongodb_uri:
        print("FAIL: no MongoDB URI in settings")
        return 2

    from pymongo import MongoClient

    # The collection user may not create or drop databases, so the smoke lives in a
    # throwaway collection inside the authorized database and is dropped at the end.
    collection_name = f"ai26_smoke_jobs_{uuid.uuid4().hex[:12]}"
    client: Any = MongoClient(
        settings.mongodb_uri, serverSelectionTimeoutMS=settings.mongodb_connect_timeout_ms
    )
    checks: list[tuple[str, bool, str]] = []
    try:
        client.admin.command("ping")
        checks.append(("mongo reachable", True, "ping ok"))
        db = client[settings.mongodb_database]
        jobs = db[collection_name]
        clock = MutableClock()
        store = JobLeaseStore(jobs, clock=clock)
        store.ensure_indexes()

        store.enqueue(
            [
                {"job_id": "x1", "kind": "x_account", "priority": 1},
                {"job_id": "ig1", "kind": "instagram_account", "priority": 1},
                {"job_id": "w1", "kind": "web_source", "priority": 2},
            ]
        )
        checks.append(("enqueue", jobs.count_documents({}) == 3, "3 jobs queued"))

        laskin = store.claim("laskin", LASKIN_CAPABILITIES, limit=5)
        kinds = {j["kind"] for j in laskin}
        checks.append(
            (
                "laskin refused browser work",
                kinds.isdisjoint(BROWSER_REQUIRED_KINDS) and [j["_id"] for j in laskin] == ["w1"],
                f"claimed={[j['_id'] for j in laskin]}",
            )
        )

        desktop = store.claim("desktop", LOCALHOST_CAPABILITIES, limit=5)
        claimed_ids = [j["_id"] for j in desktop]
        checks.append(
            ("localhost claimed browser work", set(claimed_ids) == {"x1", "ig1"}, f"claimed={claimed_ids}")
        )
        checks.append(
            (
                "no job claimed twice",
                len(claimed_ids) + len(laskin) == len(set(claimed_ids) | {j["_id"] for j in laskin}),
                "disjoint claims",
            )
        )

        clock.offset = 10_000
        reaped = store.reap_expired()
        checks.append(("expired leases reaped", reaped == 3, f"reaped={reaped}"))

        again = store.claim("laskin", LASKIN_CAPABILITIES, limit=1)
        checks.append(("reaped work reclaimable", [j["_id"] for j in again] == ["w1"], "w1 reclaimed"))

        store.complete("w1", "laskin", outcome="ok")
        second = store.complete("w1", "laskin", outcome="ok")
        checks.append(("completion idempotent", second is False, "second complete is a no-op"))

        status = store.status()
        checks.append(
            ("status reports queue", status["by_status"].get("done") == 1, str(status["by_status"]))
        )
    finally:
        client[settings.mongodb_database][collection_name].drop()
        client.close()

    width = max(len(name) for name, _, _ in checks)
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    failed = [name for name, ok, _ in checks if not ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed; {collection_name} dropped after run")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
