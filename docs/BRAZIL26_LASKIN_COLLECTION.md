# Brazil26 collection on Laskin

Brazil26 uses one canonical Phase 1 namespace across localhost and Laskin. Localhost owns all interactive Firefox/browser collection. Laskin runs only bounded non-browser collection and shared media/file processing.

The operational study overlay remains private and is derived from:

`LaclauGPT-Private/collection/brazil26/brazil-election-2026.yaml`

Do not fork Brazil26 study semantics for Laskin. Machine identity is provenance only.

## Runtime contract

Prepare the public-safe runtime skeleton and then point the ignored runtime environment to the approved private overlay:

```bash
mkdir -p data/config data/logs data/tmp
cp configs/studies/brazil26.example.yaml data/config/brazil26.yaml
cp configs/studies/brazil26.sources.example.toml data/config/brazil26.sources.toml
```

The Laskin environment must use:

```text
LACLAUGPT_PROJECT_ID=brazil26
LACLAUGPT_MACHINE=linux-server
LACLAUGPT_EXECUTION=cron
LACLAUGPT_BROWSER=none
LACLAUGPT_CALLER=laskin-cron
LACLAUGPT_RECORD_BACKEND=mongodb
LACLAUGPT_OBJECT_BACKEND=s3
LACLAUGPT_CACHE_BACKEND=redis
LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND=redis
```

MongoDB, Redis and Allas/S3 endpoints must be the same Brazil26 remote services used by localhost. The project namespace creates study isolation automatically: MongoDB records use `brazil26__records`, Redis uses `laclaugpt:brazil26`, and object keys live under `projects/brazil26/`.

Never reuse AI26 as the project id. The wrappers fail closed if `LACLAUGPT_PROJECT_ID` is anything except `brazil26` or if `LACLAUGPT_BROWSER` is not `none`.

## Validate the Laskin profile

```bash
set -a; . ./.env; set +a
.venv/bin/laclaugpt-collect doctor --profile configs/brazil26.laskin-remote.example.toml
.venv/bin/laclaugpt-collect distributed-check --study-config data/config/brazil26.yaml
```

The checked-in profile has `browser = "none"` and exposes no Firefox backend.

## One bounded non-browser tick

```bash
bash scripts/run_brazil26_laskin_collect.sh
```

The wrapper uses the canonical Phase 1 RSS/non-browser runner, passes `collection_id=brazil26`, applies the configured study/source manifest, and exits after one bounded cycle. Re-running a cycle is idempotent because canonical record identity is scoped by project/collection and canonical source identity.

To reproduce cron's minimal environment:

```bash
env -i LACLAUGPT_ENV_FILE="$PWD/.env" /bin/bash scripts/run_brazil26_laskin_collect.sh
```

## One bounded media/file tick

```bash
bash scripts/run_brazil26_laskin_media.sh
```

The distributed media runner discovers unresolved Brazil26 media references from the shared canonical MongoDB collection first, with local JSONL only as a recovery fallback. Therefore an object captured by localhost Firefox can be discovered and processed by Laskin without creating a machine-specific queue or record identity.

Completed objects use deterministic Brazil26 S3/Allas keys and refresh the same canonical MongoDB records with object/checksum state.

## Cron

Both wrappers use non-blocking `flock`; an overlapping invocation exits successfully instead of stacking.

```cron
12 * * * * /bin/bash <absolute-repo-path>/scripts/run_brazil26_laskin_collect.sh >> <absolute-repo-path>/data/logs/brazil26-laskin-collect.log 2>&1
32 * * * * /bin/bash <absolute-repo-path>/scripts/run_brazil26_laskin_media.sh >> <absolute-repo-path>/data/logs/brazil26-laskin-media.log 2>&1
```

The offsets are deliberately separate from the AI26 example schedule so concurrent studies do not stampede the same remote services.

## Smoke test

1. `doctor` accepts `configs/brazil26.laskin-remote.example.toml`.
2. The profile reports browser mode `none`.
3. One collection tick succeeds or safely deduplicates existing Brazil26 records.
4. Canonical records retain `collection_id=brazil26`.
5. One pending media reference created by localhost is visible to the Laskin media worker.
6. The resulting object lives under the Brazil26 object prefix and refreshes the Brazil26 Mongo record.
7. Re-running both ticks is idempotent.
8. A deliberate overlap exits via `flock`.
9. AI26 and Brazil26 MongoDB, Redis and S3 namespaces remain distinct.
10. No X, Instagram, TikTok or Firefox browser backend runs on Laskin.
