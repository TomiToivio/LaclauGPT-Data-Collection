# AI26 distributed collection smoke test

This is the first bounded step of the three-machine distributed test from issue #16.
It keeps the Firefox backend bound to localhost, then mirrors a small batch of the
canonical capture output to the shared MongoDB + S3/CSC Allas + Redis plane.

The public repository contains no AI26 source lists, credentials, researcher notes,
or unpublished study settings. The real study YAML must live below the runtime path
set in `LACLAUGPT_PRIVATE_CONFIG_DIR`.

## 1. Install the distributed extras

```bash
python -m pip install -e '.[distributed]'
```

## 2. Export the shared run contract

Use the same `LACLAUGPT_RUN_ID` on the laptop and Linux server.

```bash
export LACLAUGPT_PROJECT_ID=ai26
export LACLAUGPT_RUN_ID=ai26-smoke-001
export LACLAUGPT_PRIVATE_CONFIG_DIR=/path/to/private/runtime/config

export LACLAUGPT_RECORD_BACKEND=mongodb
export LACLAUGPT_OBJECT_BACKEND=s3
export LACLAUGPT_CACHE_BACKEND=redis
export LACLAUGPT_MESSAGING_BACKEND=redis

export LACLAUGPT_MONGODB_URI='mongodb://...'
export LACLAUGPT_REDIS_URL='redis://...'
export LACLAUGPT_S3_ENDPOINT='https://object-storage.example'
export LACLAUGPT_S3_BUCKET='...'
export LACLAUGPT_S3_ACCESS_KEY='...'
export LACLAUGPT_S3_SECRET_KEY='...'
```

Do not paste these values into tracked files.

## 3. Validate before collecting

```bash
laclaugpt-collect doctor
laclaugpt-collect distributed-check \
  --study-config "$LACLAUGPT_PRIVATE_CONFIG_DIR/ai26.yaml"
```

Distributed mode fails closed when the project ID, run ID, private config root, Redis,
or S3 bucket is missing. The study config must resolve inside the private config root.

## 4. Run Firefox collection locally

The browser extension still talks only to localhost.

```bash
laclaugpt-collect capture-server \
  --study-config "$LACLAUGPT_PRIVATE_CONFIG_DIR/ai26.yaml" \
  --data-root ./data/browser-ai26 \
  --host 127.0.0.1 \
  --port 8765
```

Collect only a bounded private smoke sample. Do not start the full AI26 corpus run.

## 5. Mirror a bounded batch to the distributed plane

In another terminal:

```bash
laclaugpt-collect distributed-sync \
  --study-config "$LACLAUGPT_PRIVATE_CONFIG_DIR/ai26.yaml" \
  --data-root ./data/browser-ai26 \
  --limit 25
```

The worker:

- reads canonical JSONL emitted by the Firefox backend;
- uploads inline raw payloads to `projects/ai26/runs/<run_id>/raw/...` in S3/Allas;
- upserts canonical records idempotently by canonical `source_url` into `ai26__records`;
- publishes only `project_id`, `run_id`, `source_url`, MongoDB collection name, and raw object reference to the Redis `collected` stream;
- uses a run-scoped Redis lease to avoid repeatedly re-emitting the same record during frequent cron polling.

A one-minute laptop bridge can be rendered with:

```bash
laclaugpt-collect schedule cron \
  --schedule '* * * * *' \
  --command-line "laclaugpt-collect distributed-sync --study-config $LACLAUGPT_PRIVATE_CONFIG_DIR/ai26.yaml --data-root ./data/browser-ai26 --limit 25"
```

## 6. Linux-server half

Use the same environment contract and `LACLAUGPT_RUN_ID` for non-browser collectors on
the Linux server. Their canonical records should target the same `ai26__records` MongoDB
collection and project-scoped Redis/S3 namespaces. Source identity remains the dedup key,
so simultaneous laptop/server writes converge on one logical record.

## Current boundary

This implementation intentionally uses a local-to-distributed bridge for Firefox as the
first smoke-test step. The capture server itself remains localhost-only and preserves its
local SQLite/JSONL recovery copy. A later iteration can call the same distributed sink
directly after each capture, without changing the MongoDB/Redis/Allas contract.
