# AI26 distributed collection smoke test

This is the bounded Collection-side path for the three-machine distributed test from issue #16. The laptop keeps Firefox bound to localhost while both laptop and Linux-server workers write into the same MongoDB + S3/CSC Allas + Redis project/run namespace.

The public repository contains no private AI26 credentials, researcher notes, or unpublished operational source lists. Real study/source configuration must live below the runtime path set in `LACLAUGPT_PRIVATE_CONFIG_DIR`.

## 1. Install the distributed extras

On the laptop:

```bash
python -m pip install -e '.[distributed]'
```

On the Linux server, install the complete Phase 1 non-browser dependency set:

```bash
python -m pip install -e '.[distributed,phase1-non-browser]'
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

export LACLAUGPT_MONGODB_URI='mongodb://...:27017/...'
export LACLAUGPT_REDIS_URL='redis://...'
export LACLAUGPT_S3_ENDPOINT='https://object-storage.example'
export LACLAUGPT_S3_BUCKET='...'
export LACLAUGPT_S3_ACCESS_KEY='...'
export LACLAUGPT_S3_SECRET_KEY='...'
```

Do not paste these values into tracked files.

## 3. Validate before collecting

On both machines:

```bash
laclaugpt-collect doctor
```

On the laptop, validate the browser study configuration:

```bash
laclaugpt-collect distributed-check \
  --study-config "$LACLAUGPT_PRIVATE_CONFIG_DIR/ai26.yaml"
```

Distributed mode fails closed when the project ID, run ID, private config root, Redis, or S3 bucket is missing. Private configuration paths must resolve below `LACLAUGPT_PRIVATE_CONFIG_DIR`.

## 4. Laptop: run Firefox collection locally

The browser extension still talks only to localhost.

```bash
laclaugpt-collect capture-server \
  --study-config "$LACLAUGPT_PRIVATE_CONFIG_DIR/ai26.yaml" \
  --data-root ./data/browser-ai26 \
  --host 127.0.0.1 \
  --port 8765
```

Collect only a bounded private smoke sample. Do not start the full AI26 corpus run.

In another laptop terminal, mirror a bounded batch to the shared plane:

```bash
laclaugpt-collect distributed-sync \
  --study-config "$LACLAUGPT_PRIVATE_CONFIG_DIR/ai26.yaml" \
  --data-root ./data/browser-ai26 \
  --limit 25
```

If the sample contains media, immediately persist the pending files to Allas/S3 and refresh MongoDB readiness:

```bash
laclaugpt-distributed-media \
  --study-config "$LACLAUGPT_PRIVATE_CONFIG_DIR/ai26.yaml" \
  --data-root ./data/browser-ai26 \
  --workers 4 \
  --limit 25
```

## 5. Linux server: join the same run with RSS

The first non-browser distributed worker reads the standard `[[feed]]` TOML source-manifest convention. Point it at a private bounded AI26 manifest under the private config root:

```bash
laclaugpt-server-rss \
  --source-manifest "$LACLAUGPT_PRIVATE_CONFIG_DIR/ai26.sources.toml" \
  --collection-id ai26 \
  --worker-id linux-server-rss-01 \
  --max-feeds 5 \
  --per-feed-limit 5 \
  --limit 20
```

The worker uses the same `project_id=ai26` and `LACLAUGPT_RUN_ID` as the laptop. It:

- collects a bounded RSS/Atom sample using the existing generic RSS collector;
- accepts ISO timestamps and normal RSS/RFC publication timestamps;
- applies the AI26 source-publication floor before distributed ingestion;
- sorts eligible records by the shared handoff priority/newest-first contract;
- stamps collection, source-manifest and worker provenance without copying the private manifest into MongoDB or logs;
- acquires a run-scoped Redis lease for each source revision;
- writes canonical/raw state through the same MongoDB + Allas/S3 distributed sink as Firefox; and
- emits the same lightweight `collected` and `analysis-ready` references.

For frequent server polling, a conservative cron example is:

```cron
*/5 * * * * cd /opt/LaclauGPT-Data-Collection && laclaugpt-server-rss --source-manifest "$LACLAUGPT_PRIVATE_CONFIG_DIR/ai26.sources.toml" --collection-id ai26 --worker-id linux-server-rss-01 --max-feeds 5 --per-feed-limit 5 --limit 20 >> data/logs/server-rss.log 2>&1
```

Keep secrets/environment loading outside the tracked crontab command when possible, for example via the service account's private environment or an ignored wrapper script.

## 6. What should appear in the shared backends

Both machines target the same project namespace:

```text
MongoDB: ai26__records
Redis:   laclaugpt:ai26:...
Allas:   projects/ai26/...
```

MongoDB identity is collection-aware and canonical-source based, so simultaneous laptop/server writes converge safely rather than creating port-specific datasets. Redis carries references/leases/events, not large source payloads. Large/raw/media objects go to S3/Allas.

Ready records expose the Collection → Analysis handoff contract in MongoDB and optionally the Redis `analysis-ready` stream. The Analysis worker can therefore start independently on another machine without changing Collection's storage contract.

## 7. Minimal first-test sequence

Use one shared run ID and keep every bound small:

```text
Laptop Firefox capture
        ↓
laptop distributed-sync ───────┐
        ↓                       │
optional distributed-media     │
                                ├─→ MongoDB / Redis / Allas
Linux-server RSS collector ─────┘
                                ↓
                         analysis-ready records
```

Verify counts and a few source identities in MongoDB/Allas before increasing limits. This smoke test is deliberately not a full-corpus run.
