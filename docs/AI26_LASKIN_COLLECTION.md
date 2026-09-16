# AI26 collection on Laskin

This is the unattended server profile for AI26 on **Laskin**, administered over SSH. It reuses the same AI26 research configuration, MongoDB namespace, Redis configuration plane and CSC Allas/S3 layout as the localhost/laptop profile from issue #50.

Firefox/browser-assisted capture stays on the researcher's laptop. Laskin runs bounded non-browser collection and file/media processing hourly.

The checked-in AI26 files are public methodology/templates only. Copy them below ignored `data/config/` before use. Never commit credentials, private endpoints, cookies, private watch lists or real runtime target overlays.

## 1. SSH and install

From the researcher's workstation:

```bash
ssh laskin
```

Use the existing SSH configuration/key setup. No root access is required for the normal user-level deployment.

On Laskin:

```bash
git clone https://github.com/TomiToivio/LaclauGPT-Data-Collection.git
cd LaclauGPT-Data-Collection
python -m venv .venv
source .venv/bin/activate
pip install -e '.[distributed,feeds,youtube,documents]'
mkdir -p data/config data/logs data/tmp
cp configs/studies/ai26.example.yaml data/config/ai26.yaml
cp configs/studies/ai26.sources.example.toml data/config/ai26.sources.toml
cp configs/studies/ai26.collection-codebook.yaml data/config/ai26.collection-codebook.yaml
cp .env.example data/config/ai26-laskin.env
```

Edit only the ignored `data/config/ai26-laskin.env`. Set the same remote services used by the laptop profile:

```bash
LACLAUGPT_PROJECT_ID=ai26
LACLAUGPT_PROFILE=ai26-laskin-remote
LACLAUGPT_MACHINE=linux-server
LACLAUGPT_EXECUTION=cron
LACLAUGPT_BROWSER=none
LACLAUGPT_CALLER=laskin-cron
LACLAUGPT_PRIVATE_CONFIG_DIR=./data/config
LACLAUGPT_DATA_ROOT=./data
LACLAUGPT_RECORD_BACKEND=mongodb
LACLAUGPT_OBJECT_BACKEND=s3
LACLAUGPT_CACHE_BACKEND=memory
LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND=redis
LACLAUGPT_MESSAGING_BACKEND=none
LACLAUGPT_TASK_QUEUE_BACKEND=direct
LACLAUGPT_MONGODB_URI=<same remote MongoDB URI as AI26 laptop>
LACLAUGPT_MONGODB_DATABASE=laclaugpt
LACLAUGPT_REDIS_URL=<same remote Redis URL as AI26 laptop>
LACLAUGPT_S3_ENDPOINT=<CSC Allas S3 endpoint>
LACLAUGPT_S3_REGION=<region>
LACLAUGPT_S3_BUCKET=<same AI26 bucket>
LACLAUGPT_S3_ACCESS_KEY=<private value>
LACLAUGPT_S3_SECRET_KEY=<private value>
LACLAUGPT_S3_SIGNATURE_VERSION=s3
LACLAUGPT_S3_ADDRESSING_STYLE=auto
```

Do not invent a Laskin-specific MongoDB database or Allas project tree. Machine identity is provenance, not canonical record identity.

## 2. Validate the profile

```bash
set -a
source data/config/ai26-laskin.env
set +a

laclaugpt-collect doctor --profile configs/ai26.laskin-remote.example.toml
laclaugpt-collect distributed-check --study-config data/config/ai26.yaml
```

The commands must not print secrets.

## 3. Manual collection test

Run one bounded non-browser cycle before installing cron:

```bash
bash scripts/run_ai26_laskin_collect.sh
```

The current canonical unattended worker intentionally begins with RSS/Atom, using the same bounded AI26 source manifest as the localhost setup. RSS/blog/newsletter collection is the high-signal, low-friction baseline. Additional canonical collectors should join this runner rather than creating a second scheduler or schema.

The wrapper uses `flock`, so a second overlapping invocation exits cleanly.

## 4. Manual file/media test

```bash
bash scripts/run_ai26_laskin_media.sh
```

The existing distributed media worker downloads pending media referenced by canonical records available in Laskin's configured data root, stores deterministic objects in CSC Allas/S3, persists checksums/download state and refreshes affected canonical MongoDB records.

### Current cross-machine limitation

Redis task queueing is intentionally disabled for AI26 at present, matching issue #50. Therefore Laskin does **not yet automatically consume every laptop-only browser media reference from a central Redis queue**. Browser captures first need to reach a canonical record path visible to the distributed media workflow. Keep this limitation explicit until the repository's shared MongoDB/Redis download-job reader is implemented.

## 5. Hourly cron jobs

Edit the user's crontab:

```bash
crontab -e
```

Add staggered hourly jobs:

```cron
5 * * * * cd /path/to/LaclauGPT-Data-Collection && bash scripts/run_ai26_laskin_collect.sh >> data/logs/ai26-laskin-collect.log 2>&1
20 * * * * cd /path/to/LaclauGPT-Data-Collection && bash scripts/run_ai26_laskin_media.sh >> data/logs/ai26-laskin-media.log 2>&1
```

Both commands run once and exit. Cron is the scheduler. No nested long-lived scheduler is started.

Secrets are loaded from `data/config/ai26-laskin.env`; never place credentials directly in crontab.

## 6. Hermes for AI26

Hermes is an optional orchestration/research agent. Collection must remain operable without Hermes, but Hermes itself is not intentionally reduced in capability.

The public-safe profile is:

```text
configs/hermes-ai26.example.toml
```

Current Hermes model:

```text
deepseek-v4.1-flash:cloud
```

The important constraint is not model capability. It is **configuration retrieval**: Hermes must load the AI26 study design, source manifest and codebook from the repository instead of trying to remember or reconstruct them.

Before Hermes plans AI26 collection, it must inspect:

```text
configs/studies/ai26.example.yaml
configs/studies/ai26.sources.example.toml
configs/studies/ai26.collection-codebook.yaml
```

If private runtime copies exist, they normally live at:

```text
data/config/ai26.yaml
data/config/ai26.sources.toml
data/config/ai26.collection-codebook.yaml
```

The checked-in templates remain the public methodological baseline. Private runtime files may extend them but must not be committed.

### Why this is explicit

Historical Hermes/CyborgAnthropology code contained useful source lists, codebook ideas and monitoring patterns, but an agent should not have to discover them by guessing repository history. Current canonical AI26 files come first. Legacy repositories are consulted only to recover useful public-safe items that are genuinely missing from current configuration.

Useful recovered source families include rationalist/alignment, AI safety/x-risk, acceleration/techno-optimist discourse, Critical AI/political economy, labour and creative-rights debates, policy/regulation, frontier labs, scholarly AI research and technology journalism. These are sampling/discovery families, not automatic ideology labels.

### Hermes operation

Hermes may inspect redacted configuration, compare source coverage, identify possible gaps, propose bounded source additions, validate deployment profiles and plan or invoke canonical collectors when explicitly permitted.

Hermes must not create a second crawler architecture, invent a replacement AI26 taxonomy, silently modify private target lists, or perform final ideological classification in the Collection module.

## 7. Analysis model handoff

Collection and Hermes orchestration are distinct from downstream discourse analysis. The current default analytics model family is:

```text
gemma4:12b
gemma4:31b-cloud
gemma4:e2b
```

When an agent works across Collection and Analysis, do not silently use the Hermes model in place of these analytical models. Preserve model/prompt provenance for any persisted model-assisted result.

## 8. AI26 settings shared with the laptop

Do not fork the research design for Laskin. Both machines use the same logical configuration:

```text
configs/studies/ai26.example.yaml
configs/studies/ai26.sources.example.toml
configs/studies/ai26.collection-codebook.yaml
```

Operational copies live under ignored `data/config/`.

The bounded source design covers contrasting AI imaginaries and arenas, including acceleration/techno-optimism, x-risk/safety, Critical AI, labour/rights, pause/anti-AI mobilisation, policy/parliamentary discourse and frontier-lab/industry discourse. These are sampling/sensitizing categories, not labels automatically assigned to actors or documents.

## 9. Inspect status over SSH

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
set -a; source data/config/ai26-laskin.env; set +a
laclaugpt-collect doctor --profile configs/ai26.laskin-remote.example.toml
laclaugpt-collect distributed-check --study-config data/config/ai26.yaml
```

Lock files live under `data/tmp/`. Their presence alone does not mean a process is active; `flock` ownership is authoritative.

## 10. Update safely

```bash
cd /path/to/LaclauGPT-Data-Collection
git pull
source .venv/bin/activate
pip install -e '.[distributed,feeds,youtube,documents]'
```

Then rerun the profile check and one manual collection cycle before relying on the next cron invocation.

## 11. Smoke test

1. SSH login succeeds.
2. Virtual environment/package loads.
3. `doctor` validates `ai26-laskin-remote`.
4. MongoDB/Redis/Allas distributed check succeeds.
5. One public-safe RSS item is collected or safely deduplicated.
6. The canonical record carries `project_id=ai26` and Laskin worker provenance without making the machine part of source identity.
7. One small public-safe media object can be processed from a locally available canonical record.
8. The object appears under the common AI26 Allas/S3 prefix and canonical metadata receives object/checksum state.
9. Rerunning the wrappers does not duplicate canonical records/object identities.
10. `crontab -l` shows both hourly jobs.
11. A deliberately overlapping wrapper invocation exits via `flock`.
12. Logs contain status information without credentials/tokens.
13. Hermes can locate the three canonical AI26 files and report their roles without using model memory as the source of truth.
