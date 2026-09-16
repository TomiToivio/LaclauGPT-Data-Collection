# Two-machine collection pattern: manual researcher host + cron collector host

This document describes the two-role deployment pattern used for the AI26
distributed run ([issue #16](https://github.com/TomiToivio/LaclauGPT-Data-Collection/issues/16)):
one **manually operated researcher host** with browser capture, and one
**unattended cron host** running network collectors.

Both roles write into a single shared namespace over MongoDB + Redis +
S3-compatible object storage. Only generic paths and environment variable names
appear here: hostnames, private paths and credentials are supplied at runtime
and never committed. See [PRIVACY.md](PRIVACY.md) and [RUNTIME_DATA.md](RUNTIME_DATA.md).

## Role split

| Role | `LACLAUGPT_MACHINE` | `LACLAUGPT_EXECUTION` | `LACLAUGPT_BROWSER` | Operation |
|---|---|---|---|---|
| Researcher host | `laptop` | `cli` | `firefox-local` | Manual, researcher-driven |
| Collector host | `linux-server` | `cron` | `none` | Unattended, scheduled |

The split is deliberate: browser capture requires an interactive session and
stays researcher-controlled, while feed polling should not depend on anyone
being logged in.

## Shared run contract

Both hosts export the same project and run identity, and the same backend
selection:

```bash
export LACLAUGPT_PROJECT_ID=<project>
export LACLAUGPT_RUN_ID=<run>
export LACLAUGPT_PRIVATE_CONFIG_DIR=<private-config-root>

export LACLAUGPT_RECORD_BACKEND=mongodb
export LACLAUGPT_OBJECT_BACKEND=s3
export LACLAUGPT_CACHE_BACKEND=redis
export LACLAUGPT_MESSAGING_BACKEND=redis

export LACLAUGPT_MONGODB_URI=<private>
export LACLAUGPT_MONGODB_DATABASE=<private>
export LACLAUGPT_REDIS_URL=<private>
export LACLAUGPT_S3_ENDPOINT_URL=<private>
export LACLAUGPT_S3_REGION=<private>
export LACLAUGPT_S3_BUCKET=<private>
export LACLAUGPT_S3_ACCESS_KEY_ID=<private>
export LACLAUGPT_S3_SECRET_ACCESS_KEY=<private>
```

Both hosts must agree on `LACLAUGPT_RUN_ID`; records, objects and events carry
it as provenance. Distributed mode fails closed when the project ID, run ID,
private config root, Redis or bucket is missing.

## Role 1: researcher host (manual)

Validate first:

```bash
laclaugpt-collect doctor
```

Start the localhost-only browser backend. `firefox-local` is rejected if it is
asked to bind to anything other than loopback:

```bash
laclaugpt-collect capture-server \
  --study-config "$LACLAUGPT_PRIVATE_CONFIG_DIR/<study>.yaml" \
  --data-root ./data/browser \
  --host 127.0.0.1 --port 8765
```

Mirror a bounded batch of captured records into the shared plane:

```bash
laclaugpt-collect distributed-sync \
  --study-config "$LACLAUGPT_PRIVATE_CONFIG_DIR/<study>.yaml" \
  --data-root ./data/browser \
  --limit 25
```

Persist pending media and refresh downstream readiness, if the sample has any:

```bash
laclaugpt-distributed-media \
  --study-config "$LACLAUGPT_PRIVATE_CONFIG_DIR/<study>.yaml" \
  --data-root ./data/browser \
  --workers 4 --limit 25
```

Keep `--limit` small while validating. This is a bounded test path, not a
full-corpus run. Nothing on this host is scheduled.

## Role 2: collector host (cron)

Non-browser collectors run against the same run and backends. Start with RSS,
the lowest-friction source family:

```bash
laclaugpt-server-rss \
  --source-manifest "$LACLAUGPT_PRIVATE_CONFIG_DIR/<study>.sources.toml" \
  --collection-id <project> \
  --worker-id <worker-label> \
  --max-feeds 4 --per-feed-limit 4 --limit 10
```

The worker reads the standard `[[feed]]` TOML manifest convention, applies the
study's source-publication floor, orders eligible records by the shared
handoff priority, acquires a run-scoped lease per source revision, writes
through the same distributed sink, and emits the same reference-only events.

### Cron requires an explicit environment

This is the one non-obvious part of the cron role. Configuration tools that
export credentials into an **interactive shell** — CSC's `allas-conf` is the
canonical example — do **not** reach cron, because cron does not inherit an
interactive shell. A collector that works when you run it by hand will fail
under cron for this reason alone.

The fix is to make the scheduled job load its own runtime environment:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="<absolute-repo-path>"

# Load the private runtime contract; cron inherits no interactive shell.
set -a
. "${REPO_ROOT}/.env"
set +a

# Prevent overlapping ticks.
exec 9>"${REPO_ROOT}/data/runs/collection.lock"
flock -n 9 || exit 0

cd "${REPO_ROOT}"
"${REPO_ROOT}/.venv/bin/laclaugpt-server-rss" \
  --source-manifest "${LACLAUGPT_PRIVATE_CONFIG_DIR}/<study>.sources.toml" \
  --collection-id "${LACLAUGPT_PROJECT_ID}" \
  --worker-id <worker-label> \
  --max-feeds 4 --per-feed-limit 4 --limit 10
```

Then schedule it:

```cron
*/15 * * * * /bin/bash <absolute-repo-path>/data/runtime/collect-rss.sh
```

Design notes for the schedule:

- **`flock` prevents overlap.** If a tick runs long, the next one exits
  cleanly instead of stacking.
- **Bounds stay small** so each tick is cheap and the stream stays steady
  rather than bursting.
- **Append to a dated log** under the ignored `data/logs/` tree so a tick's
  outcome is auditable without a terminal.
- **Keep the wrapper inside the runtime tree** (`data/`), which is gitignored:
  it embeds an absolute machine path and must not be committed.

Rehearse a tick under an empty environment, which is what cron actually
provides:

```bash
env -i /bin/bash <absolute-repo-path>/data/runtime/collect-rss.sh
```

### Pause and resume

```bash
crontab -l > ~/crontab.backup          # always back up first
crontab -l | grep -v 'collect-rss.sh' | crontab -      # pause
( crontab -l; echo '*/15 * * * * /bin/bash <repo>/data/runtime/collect-rss.sh' ) | crontab -
```

## Verifying the shared plane

Both roles should produce the same observable shape:

```text
MongoDB  <project>__records
Redis    laclaugpt:<project>:...
Allas    projects/<project>/...
```

- MongoDB holds the canonical record plus a `handoff` block (`status`,
  `source_priority`, `handoff_key`).
- Object storage holds raw payloads at
  `projects/<project>/runs/<run_id>/raw/<sha256>.json`.
- Redis streams (`collected`, `analysis-ready`) carry **references only** —
  identity, run and raw refs — never large payloads or credentials.

Check record counts by machine and handoff status:

```bash
python - <<'PY'
import pymongo
from laclaugpt_data_collection.config import Settings  # reads .env

s = Settings()
coll = pymongo.MongoClient(s.mongodb_uri)[s.mongodb_database][
    s.distributed_namespace.mongo_collection("records")
]
for row in coll.aggregate([
    {"$match": {"project_id": s.project_id}},
    {"$group": {"_id": "$handoff.status", "n": {"$sum": 1}}},
]):
    print(row["_id"], row["n"])
PY
```

## Idempotency

Collection writes are idempotent on canonical source identity
(`project_id` + `collection_id` + canonical `source_url`), and each worker
holds a run-scoped lease per source revision. The two roles can therefore
collect concurrently without duplicating a logical record, and re-running any
collector is safe. A rising `duplicate_leases` count in worker output is
expected and healthy — it means already-collected sources were skipped.

## CSC Allas upload notes

Allas is not fully S3-compatible, and both differences affect uploads only, so
a wrong client configuration looks healthy until the first write:

| Symptom | Cause | Setting |
|---|---|---|
| `MissingContentLength` (HTTP 411) on PUT | Allas rejects signature v4 uploads | `LACLAUGPT_S3_SIGNATURE_VERSION=s3` |
| `QuotaExceeded` (HTTP 403) on PUT, even with free space | Allas rejects path-style addressing | `LACLAUGPT_S3_ADDRESSING_STYLE=auto` |

Both defaults are already correct. The `QuotaExceeded` case is worth knowing:
it is a misleading error code and does **not** indicate exhausted CSC project
quota. Reads succeed with any combination, which is why the defect only appears
on the first upload.

## Boundaries

- Never commit `.env`, credentials, private paths, hostnames, source lists,
  manifests or collected data. Runtime material stays below the ignored `data/`
  tree or in an external secret store.
- `LACLAUGPT_PRIVATE_CONFIG_DIR` is a fail-closed gate: distributed collection
  refuses to run unless the study config resolves below that root. The check
  uses `resolve()`, which follows symlinks, so the config must be a **real file
  inside** the root — a symlink pointing outside it is rejected.
- The browser role binds to loopback only and remains researcher-controlled.
- Only the collector host is scheduled. If unattended collection is wanted, it
  belongs there, not on the researcher host.
