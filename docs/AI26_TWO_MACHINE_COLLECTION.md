# AI26 two-machine collection

This is the shared runbook for the AI26 distributed collection run. It covers the two roles that write into one canonical scientific corpus:

```text
researcher laptop   manual, browser-assisted capture, CLI execution
Laskin              unattended cron collectors + media/file worker
        \           /
         shared remote services
          MongoDB  Redis  CSC Allas/S3
         one canonical ai26 namespace
```

Both roles write into a **single shared namespace** over remote MongoDB + Redis + S3-compatible object storage. Only generic paths and environment variable names appear here: hostnames, private paths and credentials are supplied at runtime and never committed. See [PRIVACY.md](PRIVACY.md) and [RUNTIME_DATA.md](RUNTIME_DATA.md).

The machine is **execution provenance, not study identity**. Do not create machine-specific databases, Redis namespaces, project IDs or S3 trees.

## Read this first

```text
WORKDIR (Laskin)  -> /mnt/workspace/LaclauGPT-Data-Collection
WHAT to collect   -> configs/studies/ai26.example.yaml
SOURCE manifest   -> configs/studies/ai26.sources.example.toml
COLLECTION cues   -> configs/studies/ai26.collection-codebook.yaml
THEORY/design     -> LaclauGPT paper/PHASE_1_PAPER.md
                     (https://github.com/TomiToivio/LaclauGPT/blob/main/paper/PHASE_1_PAPER.md)

Laskin:
  cron collectors  -> scripts/run_ai26_laskin_collect.sh   (hourly :10)
  cron media worker-> scripts/run_ai26_laskin_media.sh     (hourly :30)
  no Firefox/browser/X collector
  logs/status      -> data/logs/, crontab -l

Shared:
  remote MongoDB   -> canonical records / operational state
  remote Redis     -> distributed configuration + coordination
  CSC Allas/S3     -> project object storage
  canonical ai26 namespace
```

Canonical repositories (all public):

```text
TomiToivio/LaclauGPT                     meta: paper/theory, docs/reports/
TomiToivio/LaclauGPT-Data-Collection     collection + normalization
TomiToivio/LaclauGPT-Data-Analysis       analysis module
TomiToivio/LaclauGPT-Data-Visualization  visualization module
```

## Role split

| Role | `LACLAUGPT_MACHINE` | `LACLAUGPT_EXECUTION` | `LACLAUGPT_BROWSER` | Operation |
|---|---|---|---|---|
| Researcher host | `laptop` | `cli` | `firefox-local` | Manual, researcher-driven |
| Collector host (Laskin) | `linux-server` | `cron` | `none` | Unattended, scheduled |

The split is deliberate: browser capture requires an interactive session and stays researcher-controlled, while feed polling should not depend on anyone being logged in. **Laskin must never run Firefox, the browser capture server, or the X collector.**

## Shared run contract

Both hosts export the same project and run identity, and the same backend selection:

```bash
export LACLAUGPT_PROJECT_ID=ai26
export LACLAUGPT_RUN_ID=<shared run id>
export LACLAUGPT_PRIVATE_CONFIG_DIR=<private-config-root>

export LACLAUGPT_RECORD_BACKEND=mongodb
export LACLAUGPT_OBJECT_BACKEND=s3
export LACLAUGPT_CACHE_BACKEND=redis
export LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND=redis

export LACLAUGPT_MONGODB_URI=<private>
export LACLAUGPT_MONGODB_DATABASE=<private, shared>
export LACLAUGPT_REDIS_URL=<private>
export LACLAUGPT_S3_ENDPOINT_URL=<private, a3s.fi>
export LACLAUGPT_S3_REGION=<private>
export LACLAUGPT_S3_BUCKET=<private, shared>
export LACLAUGPT_S3_ACCESS_KEY_ID=<private>
export LACLAUGPT_S3_SECRET_ACCESS_KEY=<private>
```

Both hosts must agree on `LACLAUGPT_RUN_ID`; records, objects and events carry it as provenance. Distributed mode fails closed when the project ID, run ID, private config root, Redis or bucket is missing.

### Redis roles

Redis has three intentionally separate roles and AI26 opts into configuration plus coordination, not task queueing:

| Role | AI26 setting | Purpose |
|---|---|---|
| distributed configuration | `redis` | versioned, pinned configuration revisions |
| cache | `redis` | operational caching |
| messaging | `redis` | reference-only `collected` / `analysis-ready` stream events |
| task queue | `direct` | **intentionally dormant** — no queue complexity for this run |

Redis is coordination/settings/queue infrastructure, **never** the canonical record schema. Durable results stay in MongoDB and object storage.

Verify both hosts resolve the same canonical configuration:

```bash
set -a; . ./.env; set +a
.venv/bin/laclaugpt-collect doctor --profile configs/ai26.laskin-remote.example.toml
.venv/bin/laclaugpt-collect distributed-check --study-config data/config/ai26.yaml
.venv/bin/laclaugpt-redis-config show     # current pinned revision + actor
```

A configuration revision should be pinned per run so a batch cannot be silently re-interpreted halfway through. `laclaugpt-redis-config push` publishes a validated revision; `show`/`pull` read it back. Record the revision in provenance when it matters.

## Role 1: researcher host (manual)

Validate first:

```bash
laclaugpt-collect doctor
```

Start the localhost-only browser backend. `firefox-local` is rejected if it is asked to bind to anything other than loopback:

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

Keep `--limit` small while validating. This is a bounded test path, not a full-corpus run. Nothing on this host is scheduled.

## Role 2: collector host (Laskin, cron)

Non-browser collectors run against the same run and backends. Start with RSS, the lowest-friction source family:

```bash
laclaugpt-server-rss \
  --source-manifest "$LACLAUGPT_PRIVATE_CONFIG_DIR/<study>.sources.toml" \
  --collection-id ai26 \
  --worker-id <worker-label> \
  --max-feeds 8 --per-feed-limit 5 --limit 40
```

The worker reads the standard `[[feed]]` TOML manifest convention, applies the study's source-publication floor, orders eligible records by the shared handoff priority, acquires a run-scoped lease per source revision, writes through the same distributed sink, and emits the same reference-only events.

### Bounded feed windows

`--max-feeds` bounds each tick. The window is priority-ordered and **rotated once per hour**, so every manifest entry is eventually polled instead of the same leading rows forever. Each tick reports `feed_names` so the covered window is auditable. Rotation is stateless and derived from the clock; `--rotation` overrides it explicitly for tests.

### Cron requires an explicit environment

This is the one non-obvious part of the cron role. Configuration tools that export credentials into an **interactive shell** — CSC's `allas-conf` is the canonical example — do **not** reach cron, because cron does not inherit an interactive shell. A collector that works when you run it by hand will fail under cron for this reason alone.

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
exec 9>"${REPO_ROOT}/data/tmp/collection.lock"
flock -n 9 || exit 0

cd "${REPO_ROOT}"
"${REPO_ROOT}/.venv/bin/laclaugpt-server-rss" \
  --source-manifest "${LACLAUGPT_AI26_SOURCE_MANIFEST}" \
  --collection-id "${LACLAUGPT_PROJECT_ID}" \
  --worker-id laskin-cron \
  --max-feeds 8 --per-feed-limit 5 --limit 40
```

Resolve console scripts through the checkout's own `.venv/bin/` rather than relying on `PATH`: cron's `PATH` is minimal and the venv is not always activated.

Then schedule it:

```cron
10 * * * * /bin/bash <repo>/scripts/run_ai26_laskin_collect.sh >> <repo>/data/logs/ai26-laskin-collect.log 2>&1
30 * * * * /bin/bash <repo>/scripts/run_ai26_laskin_media.sh   >> <repo>/data/logs/ai26-laskin-media.log   2>&1
```

Design notes for the schedule:

- **`flock` prevents overlap.** If a tick runs long, the next one exits cleanly instead of stacking.
- **Bounds stay small** so each tick is cheap and the stream stays steady rather than bursting.
- **Stagger the jobs** (`:10` collection, `:30` media) so they do not contend for the same remote backends, and avoid the laptop-side schedule.
- **One bounded cycle per invocation.** Cron is the scheduler; never start an internal perpetual scheduler from cron.
- **Append to a dated log** under the ignored `data/logs/` tree so a tick's outcome is auditable without a terminal.
- **Keep credentials in `.env`**, never in crontab.

Rehearse a tick under an empty environment, which is what cron actually provides:

```bash
env -i /bin/bash <absolute-repo-path>/scripts/run_ai26_laskin_collect.sh
```

### Pause and resume

```bash
crontab -l > data/logs/crontab.backup.$(date -u +%Y%m%dT%H%M%SZ).txt   # always back up first
crontab -l | grep -v 'run_ai26_laskin' | crontab -                       # pause
crontab -e                                                               # resume
```

## Verifying the shared plane

Both roles should produce the same observable shape:

```text
MongoDB  <database>.<project>__records
Redis    laclaugpt:<project>:...
Allas    projects/<project>/...
```

- MongoDB holds the canonical record plus a `handoff` block (`status`, `source_priority`, `handoff_key`).
- Object storage holds raw payloads at `projects/<project>/runs/<run_id>/raw/<sha256>.json` and media at `projects/<project>/media/...`.
- Redis streams (`collected`, `analysis-ready`) carry **references only** — identity, run and raw refs — never large payloads or credentials.

Check record counts by arena and handoff status:

```bash
python - <<'PY'
import pymongo
from laclaugpt_data_collection.config import Settings  # reads .env

s = Settings()
coll = pymongo.MongoClient(s.mongodb_uri)[s.mongodb_database][
    s.distributed_namespace.mongo_collection("records")
]
for axis in ("arena", "handoff.status", "provenance.metadata.worker_id"):
    print(f"-- by {axis} --")
    for row in coll.aggregate([
        {"$match": {"project_id": s.project_id}},
        {"$group": {"_id": f"${axis}", "n": {"$sum": 1}}},
    ]):
        print("  ", row["_id"], row["n"])
PY
```

## Idempotency and provenance

Collection writes are idempotent on canonical source identity (`project_id` + `collection_id` + canonical `source_url`), and each worker holds a run-scoped lease per source revision. The two roles can therefore collect concurrently without duplicating a logical record, and re-running any collector is safe.

Validate that an item collected on both machines does **not** become a second canonical scientific record:

```bash
# duplicate (collection_id, source_url) groups must be empty
python - <<'PY'
import pymongo
from laclaugpt_data_collection.config import Settings
s = Settings()
coll = pymongo.MongoClient(s.mongodb_uri)[s.mongodb_database][
    s.distributed_namespace.mongo_collection("records")
]
dupes = list(coll.aggregate([
    {"$match": {"project_id": s.project_id}},
    {"$group": {"_id": {"c": "$collection_id", "u": "$source_url"}, "n": {"$sum": 1}}},
    {"$match": {"n": {"$gt": 1}}},
    {"$count": "dupes"},
]))
print("duplicate identity groups:", dupes or "NONE")
PY
```

A rising `duplicate_leases` count in worker output is expected and healthy — it means already-collected sources were skipped. `records_synced: 0` with positive `duplicate_leases` is a successful no-op tick, not a failure.

Worker identity (`laskin-cron`, `laptop-*`) belongs in **provenance metadata** and must never become part of scientific source identity.

## CSC Allas upload notes

Allas is not fully S3-compatible, and both differences affect uploads only, so a wrong client configuration looks healthy until the first write:

| Symptom | Cause | Setting |
|---|---|---|
| `MissingContentLength` (HTTP 411) on PUT | Allas rejects signature v4 uploads | `LACLAUGPT_S3_SIGNATURE_VERSION=s3` |
| `QuotaExceeded` (HTTP 403) on PUT, even with free space | Allas rejects path-style addressing | `LACLAUGPT_S3_ADDRESSING_STYLE=auto` |

Both defaults are already correct. The `QuotaExceeded` case is worth knowing: it is a misleading error code and does **not** indicate exhausted CSC project quota. Reads succeed with any combination, which is why the defect only appears on the first upload.

Endpoint access is configured once with CSC's `allas-conf`; in S3 mode it writes `~/.aws/credentials`, `~/.aws/config` and `~/.s3cfg`. Those are personal credentials outside Git. Note that a bucket listing may be denied independently of object access — verify a write by re-reading the object you just stored rather than by listing.

## Documentation map

| Topic | Document |
|---|---|
| Laskin runtime profile and cron | [AI26_LASKIN_COLLECTION.md](AI26_LASKIN_COLLECTION.md) |
| Localhost/laptop profile | [AI26_LOCALHOST_COLLECTION.md](AI26_LOCALHOST_COLLECTION.md) |
| Distributed smoke test | [distributed-ai26-smoke-test.md](distributed-ai26-smoke-test.md) |
| MongoDB backend | [MONGODB_BACKEND.md](MONGODB_BACKEND.md) |
| Redis control plane | [REDIS_CONTROL_PLANE.md](REDIS_CONTROL_PLANE.md) |
| Storage layout | [DISTRIBUTED_PROJECT_STORAGE.md](DISTRIBUTED_PROJECT_STORAGE.md) |
| Canonical record contract | [CANONICAL_RECORD.md](CANONICAL_RECORD.md) |
| Privacy boundary | [PRIVACY.md](PRIVACY.md) |
| Runtime data boundary | [RUNTIME_DATA.md](RUNTIME_DATA.md) |

## Boundaries

- Never commit `.env`, credentials, private paths, hostnames, source lists, manifests or collected data. Runtime material stays below the ignored `data/` tree or in an external secret store.
- `LACLAUGPT_PRIVATE_CONFIG_DIR` is a fail-closed gate: distributed collection refuses to run unless the study config resolves below that root. The check uses `resolve()`, which follows symlinks, so the config must be a **real file inside** the root — a symlink pointing outside it is rejected.
- The browser role binds to loopback only and remains researcher-controlled.
- Only the collector host is scheduled. If unattended collection is wanted, it belongs there, not on the researcher host.
- Never enable a browser/X collector on the collector host.
