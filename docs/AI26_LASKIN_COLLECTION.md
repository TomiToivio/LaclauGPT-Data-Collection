# AI26 collection on Laskin

This is the unattended server profile for AI26 on **Laskin**, administered over SSH. It reuses the same AI26 research configuration, MongoDB namespace, Redis configuration plane and CSC Allas/S3 layout as the localhost/laptop profile.

Firefox/browser-assisted capture stays on the researcher's laptop. Laskin runs bounded non-browser collection and file/media processing hourly.

## Read this first

```text
WORKDIR          -> /mnt/workspace/LaclauGPT-Data-Collection
WHAT to collect  -> configs/studies/ai26.example.yaml
SOURCE manifest  -> configs/studies/ai26.sources.example.toml
COLLECTION cues  -> configs/studies/ai26.collection-codebook.yaml
THEORY/design    -> LaclauGPT paper/PHASE_1_PAPER.md
                    (https://github.com/TomiToivio/LaclauGPT/blob/main/paper/PHASE_1_PAPER.md)

Laskin:
  cron collectors          -> scripts/run_ai26_laskin_collect.sh   (hourly :10)
  cron media worker        -> scripts/run_ai26_laskin_media.sh     (hourly :30)
  no Firefox/browser/X collector
  logs/status              -> data/logs/, data/tmp/, crontab -l

Shared:
  remote MongoDB           -> canonical records
  remote Redis             -> distributed configuration + coordination
  CSC Allas/S3             -> project object storage
  canonical ai26 namespace
```

The canonical repository layout is one meta-repository plus module repos. The AI26 source of truth lives in the meta-repo:

```text
TomiToivio/LaclauGPT                     meta: paper/theory, docs/reports/
TomiToivio/LaclauGPT-Data-Collection     this repository
TomiToivio/LaclauGPT-Data-Analysis       analysis module
TomiToivio/LaclauGPT-Data-Visualization  visualization module
```

All are public. The checked-in AI26 files are public methodology/templates only. Copy them below ignored `data/config/` before use. Never commit credentials, private endpoints, cookies, private watch lists or real runtime target overlays.

## 1. SSH and install

From the researcher's workstation:

```bash
ssh laskin
```

Use the existing SSH configuration/key setup. No root access is required for the normal user-level deployment.

On Laskin:

```bash
cd /mnt/workspace/LaclauGPT-Data-Collection
python -m venv .venv
source .venv/bin/activate
pip install -e '.[distributed,phase1-non-browser]'
mkdir -p data/config data/logs data/tmp
cp configs/studies/ai26.example.yaml data/config/ai26.yaml
cp configs/studies/ai26.sources.example.toml data/config/ai26.sources.toml
cp configs/studies/ai26.collection-codebook.yaml data/config/ai26.collection-codebook.yaml
```

The `phase1-non-browser` extra is the dependency contract for every non-browser source family declared by the shipped AI26 manifest. The runner also performs a manifest-aware preflight and exits with a setup error naming the missing extra and job kind before collection starts.\n\nRuntime credentials are supplied through the gitignored `.env` at the repository root (the wrapper loads it itself, because cron inherits no interactive shell). The relevant contract:

```bash
LACLAUGPT_PROJECT_ID=ai26
LACLAUGPT_RUN_ID=<same run id as the laptop profile>
LACLAUGPT_MACHINE=linux-server
LACLAUGPT_EXECUTION=cron
LACLAUGPT_BROWSER=none
LACLAUGPT_CALLER=laskin-cron
LACLAUGPT_PRIVATE_CONFIG_DIR=<absolute path to the ignored runtime config dir>
LACLAUGPT_DATA_ROOT=./data
LACLAUGPT_RECORD_BACKEND=mongodb
LACLAUGPT_OBJECT_BACKEND=s3
LACLAUGPT_CACHE_BACKEND=redis
LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND=redis
LACLAUGPT_MESSAGING_BACKEND=redis
LACLAUGPT_TASK_QUEUE_BACKEND=direct
LACLAUGPT_MONGODB_URI=<same remote MongoDB URI as the AI26 laptop profile>
LACLAUGPT_MONGODB_DATABASE=<same database as the laptop profile>
LACLAUGPT_REDIS_URL=<same remote Redis URL as the AI26 laptop profile>
LACLAUGPT_S3_ENDPOINT_URL=<CSC Allas S3 endpoint, a3s.fi>
LACLAUGPT_S3_REGION=<region>
LACLAUGPT_S3_BUCKET=<same AI26 bucket>
LACLAUGPT_S3_ACCESS_KEY_ID=<private value>
LACLAUGPT_S3_SECRET_ACCESS_KEY=<private value>
LACLAUGPT_S3_SIGNATURE_VERSION=s3
LACLAUGPT_S3_ADDRESSING_STYLE=auto
```

Do not invent a Laskin-specific MongoDB database or Allas project tree. Machine identity is provenance, not canonical record identity.

### Allas endpoint access

Endpoint access is configured once with CSC's `allas-conf` (see the [CSC Allas documentation](https://docs.csc.fi/fi/data/Allas/using_allas/allas-conf/)). In S3 mode it writes `~/.aws/credentials`, `~/.aws/config` and `~/.s3cfg`. Those files are personal credentials and must never be committed.

`allas-conf` exports credentials into an **interactive shell only**. Cron does not inherit an interactive shell, which is exactly why the wrappers load `.env` themselves. If you rotate an Allas key, update `.env` — rotating it only in `allas-conf` will not reach the scheduled job.

The canonical AI26 bucket/prefix is shared with the laptop profile, so no machine-specific S3 tree is created.

## 2. Validate the profile

```bash
set -a; . ./.env; set +a
.venv/bin/laclaugpt-collect doctor --profile configs/ai26.laskin-remote.example.toml
.venv/bin/laclaugpt-collect distributed-check --study-config data/config/ai26.yaml
```

The commands must not print secrets. `doctor` validates the profile offline; `distributed-check` confirms the live MongoDB/Redis/Allas control plane.

## 3. Manual collection test

Run one bounded non-browser cycle before relying on cron:

```bash
bash scripts/run_ai26_laskin_collect.sh
```

The canonical unattended worker begins with RSS/Atom, using the same bounded AI26 source manifest as the localhost setup. The Phase 1 runner writes through the same `DistributedCaptureSink` as browser collection, so records land in the shared `ai26__records` canonical collection instead of the legacy Phase 0 flat collection. RSS/blog/newsletter collection remains the high-signal, low-friction baseline. Additional canonical non-browser collectors should join this bounded runner rather than creating a second scheduler or schema.

The wrapper uses `flock`, so a second overlapping invocation exits cleanly. Reproduce cron's empty environment exactly with:

```bash
env -i /bin/bash scripts/run_ai26_laskin_collect.sh
```

### Feed-window rotation

The worker polls a bounded window of the manifest per tick rather than an unbounded firehose. The window is priority-ordered and rotated once per hour, so high-priority feeds lead each cycle while the rest of the manifest is still covered across successive ticks. Without the rotation the same first rows would be polled forever and the manifest tail would never be collected. Each tick logs `feed_names` so the covered window is auditable.

## 4. Manual file/media test

```bash
bash scripts/run_ai26_laskin_media.sh
```

The distributed media worker downloads pending media referenced by canonical records available in Laskin's configured data root, stores deterministic objects in CSC Allas/S3, persists checksums/download state and refreshes affected canonical MongoDB records.

Media discovery is **shared-plane first**. The worker queries the canonical AI26 MongoDB collection for records with unresolved media references, so browser captures created only on the researcher laptop are visible to Laskin after they have been synchronized. Local canonical JSONL under `data/normalized/` remains a recovery/debug fallback and is merged idempotently with the MongoDB candidates.

Redis task queueing remains intentionally dormant for AI26. Cross-machine media discovery does not require a central task queue: MongoDB is the durable source of canonical media references, while Redis remains available for configuration, coordination and reference-only events. A tick with no pending shared or local records is a successful no-op.

## 5. Hourly cron jobs

Cron is the scheduler. Both commands run once and exit; no nested long-lived scheduler is started.

```cron
10 * * * * /bin/bash /mnt/workspace/LaclauGPT-Data-Collection/scripts/run_ai26_laskin_collect.sh >> /mnt/workspace/LaclauGPT-Data-Collection/data/logs/ai26-laskin-collect.log 2>&1
30 * * * * /bin/bash /mnt/workspace/LaclauGPT-Data-Collection/scripts/run_ai26_laskin_media.sh >> /mnt/workspace/LaclauGPT-Data-Collection/data/logs/ai26-laskin-media.log 2>&1
```

Install or update them with:

```bash
crontab -l > data/logs/crontab.backup.$(date -u +%Y%m%dT%H%M%SZ).txt
crontab -e
```

The offsets are staggered (`:10` collection, `:30` media) so the two jobs do not contend for the same remote backends, and they deliberately avoid common laptop-side schedules.

Each wrapper takes its own `flock`, so an overlap between two ticks exits cleanly instead of stacking:

```bash
flock -n data/tmp/ai26-laskin-collect.lock -c 'sleep 15' &
bash scripts/run_ai26_laskin_collect.sh   # prints "... already running; exiting cleanly"
```

Secrets are loaded from `.env`; never place credentials directly in crontab.

## 6. AI26 settings shared with the laptop

Do not fork the research design for Laskin. Both machines use the same logical configuration:

```text
configs/studies/ai26.example.yaml
configs/studies/ai26.sources.example.toml
configs/studies/ai26.collection-codebook.yaml
```

Operational copies live under ignored `data/config/`. Laskin must resolve the same study/project ID, active collection window, source/codebook revision, remote MongoDB target, Redis configuration namespace, S3/Allas project namespace and enabled collector roles as the laptop.

The bounded source design covers contrasting AI imaginaries and arenas, including acceleration/techno-optimism, x-risk/safety, Critical AI, labour/rights, pause/anti-AI mobilisation, policy/parliamentary discourse and frontier-lab/industry discourse. These are sampling/sensitizing categories, not labels automatically assigned to actors or documents. Laskin's non-browser mix is deliberately audited for bounded gaps — left/public-interest techno-optimism, labour/union discourse, Finland/EU policy, open-source/open-weights and data-centre/energy conflict — and corrected by adding a few interpretable sources rather than an indiscriminate list.

## 7. Inspect status over SSH

Recent logs:

```bash
tail -n 100 data/logs/ai26-laskin-collect.log
tail -n 100 data/logs/ai26-laskin-media.log
```

Cron entries:

```bash
crontab -l
```

Profile/backend checks:

```bash
set -a; . ./.env; set +a
.venv/bin/laclaugpt-collect doctor --profile configs/ai26.laskin-remote.example.toml
```

Lock files live under `data/tmp/`. Their presence alone does not mean a process is active; `flock` ownership is authoritative.

A healthy tick logs one JSON line with `"status": "ok"` and `"errors": []`. `duplicate_leases` rising over time is **expected and healthy** — it means already-collected sources were skipped rather than duplicated. `records_synced: 0` with a positive `duplicate_leases` is a successful no-op tick, not a failure.

## 8. Update safely

```bash
cd /mnt/workspace/LaclauGPT-Data-Collection
git pull --ff-only origin main
source .venv/bin/activate
pip install -e '.[distributed,phase1-non-browser]'
```

An editable install means `git pull` alone updates the code; the `pip install` refresh is only needed when dependencies change. Then rerun the profile check and one manual collection cycle before relying on the next cron invocation.

## 9. Smoke test

1. Repository root resolves to `/mnt/workspace/LaclauGPT-Data-Collection`.
2. Virtual environment/package loads.
3. `doctor` validates the `ai26-laskin-remote` profile.
4. MongoDB/Redis/Allas distributed check succeeds.
5. One public-safe RSS item is collected or safely deduplicated.
6. The canonical record carries `project_id=ai26` and Laskin worker provenance without making the machine part of source identity.
7. One small public-safe media object can be processed from a locally available canonical record, and its checksum verifies on re-read from Allas.
8. The object appears under the common AI26 Allas/S3 prefix and canonical metadata receives object/checksum state.
9. Rerunning the wrappers does not duplicate canonical records/object identities.
10. `crontab -l` shows both hourly jobs.
11. A deliberately overlapping wrapper invocation exits via `flock`.
12. Logs contain status information without credentials/tokens.
13. No Firefox/browser/X collector is enabled on this host.
