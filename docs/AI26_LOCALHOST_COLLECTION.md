# AI26 localhost collection

This is the researcher-laptop profile for AI26. Firefox capture and ordinary CLI collection run locally, while canonical distributed state uses the same remote MongoDB, Redis configuration namespace and CSC Allas/S3 object storage as other AI26 workers.

The public AI26 files are methodology/templates only. Copy them under ignored `data/config/` before use. Do not commit endpoints, credentials, cookies, private target lists or browser profiles.

## 1. Install

```bash
git clone https://github.com/TomiToivio/LaclauGPT-Data-Collection.git
cd LaclauGPT-Data-Collection
python -m venv .venv
source .venv/bin/activate
pip install -e '.[distributed,feeds,youtube,documents]'
mkdir -p data/config data/logs data/tmp
cp configs/studies/ai26.example.yaml data/config/ai26.yaml
cp configs/studies/ai26.sources.example.toml data/config/ai26.sources.toml
cp .env.example data/config/ai26-localhost.env
```

Edit only `data/config/ai26-localhost.env`. At minimum set:

```bash
LACLAUGPT_PROJECT_ID=ai26
LACLAUGPT_PROFILE=ai26-localhost-remote
LACLAUGPT_MACHINE=laptop
LACLAUGPT_BROWSER=firefox-local
LACLAUGPT_PRIVATE_CONFIG_DIR=./data/config
LACLAUGPT_DATA_ROOT=./data
LACLAUGPT_RECORD_BACKEND=mongodb
LACLAUGPT_OBJECT_BACKEND=s3
LACLAUGPT_CACHE_BACKEND=memory
LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND=redis
LACLAUGPT_MESSAGING_BACKEND=none
LACLAUGPT_TASK_QUEUE_BACKEND=direct
LACLAUGPT_MONGODB_URI=<remote MongoDB URI>
LACLAUGPT_MONGODB_DATABASE=laclaugpt
LACLAUGPT_REDIS_URL=<remote Redis URL>
LACLAUGPT_S3_ENDPOINT=<CSC Allas S3 endpoint>
LACLAUGPT_S3_REGION=<region>
LACLAUGPT_S3_BUCKET=<bucket>
LACLAUGPT_S3_ACCESS_KEY=<private value>
LACLAUGPT_S3_SECRET_KEY=<private value>
LACLAUGPT_S3_SIGNATURE_VERSION=s3
LACLAUGPT_S3_ADDRESSING_STYLE=auto
```

Load it for interactive commands:

```bash
set -a
source data/config/ai26-localhost.env
set +a
```

Validate the public runtime shape and remote connectivity separately:

```bash
laclaugpt-collect doctor --profile configs/ai26.localhost-remote.example.toml
laclaugpt-collect distributed-check --study-config data/config/ai26.yaml
```

Neither command should print credentials.

## 2. Optional low-resource Ollama helper

Collection must not depend on an LLM and must not assign final ideology labels. If a lightweight local helper is useful for metadata normalization or bounded relevance triage, start from:

```text
configs/ollama-low-resource.example.toml
```

The profile consolidates conservative settings seen repeatedly in predecessor LaclauGPT/CyborgAnthropology code: deterministic temperature, `num_ctx=8192`, `top_p=0.9` and `repeat_penalty=1.1`. It intentionally uses a small local model and a short output budget instead of reviving the old large-model analysis pipelines. Final Laclau/Mouffe interpretation remains in Data Analysis.

## 3. Start Firefox backend

```bash
./scripts/run_firefox_study.sh data/config/ai26.yaml data 8765
```

The backend binds to `127.0.0.1:8765` only. Keep that default.

In another terminal, verify the backend using the documented health endpoint/current browser-capture instructions in `docs/BROWSER_CAPTURE.md`.

## 4. Load the Firefox extension

Open Firefox and go to `about:debugging`, choose **This Firefox**, then **Load Temporary Add-on** and select `browser/firefox/manifest.json`.

Use the extension with the AI26 study/backend. Captures are persisted locally first. The distributed sync wrapper mirrors canonical records to the shared remote namespace without changing their canonical source identity.

Run a manual sync:

```bash
./scripts/run_ai26_localhost_sync.sh
```

Re-running it is safe: the existing distributed sync/lease logic is responsible for deduplication.

## 5. Run non-browser collection

The current unattended non-browser worker intentionally starts with RSS/Atom, the highest-value low-friction source family already implemented for the distributed AI26 test.

```bash
./scripts/run_ai26_localhost_collect.sh
```

It uses `data/config/ai26.sources.toml`, applies bounded per-feed/batch limits and writes through the existing distributed sink to the same AI26 MongoDB/Redis/S3 namespace.

Other source collectors should be added to the same bounded runner as their canonical implementations mature. Do not create a second scheduler or parallel schema merely to add another platform.

## 6. Download media/files and upload to Allas

```bash
./scripts/run_ai26_localhost_media.sh
```

The existing distributed media worker scans locally captured canonical records, downloads pending media, stores deterministic objects in CSC Allas/S3, persists checksums/status in downloader state, and refreshes affected canonical records in MongoDB.

## 7. Cron

All wrappers use `flock`, so overlapping invocations exit cleanly instead of double-running.

Example crontab:

```cron
*/10 * * * * cd /path/to/LaclauGPT-Data-Collection && ./scripts/run_ai26_localhost_sync.sh >> data/logs/ai26-sync.log 2>&1
17 * * * * cd /path/to/LaclauGPT-Data-Collection && ./scripts/run_ai26_localhost_collect.sh >> data/logs/ai26-collect.log 2>&1
27 * * * * cd /path/to/LaclauGPT-Data-Collection && ./scripts/run_ai26_localhost_media.sh >> data/logs/ai26-media.log 2>&1
```

Do not put secrets directly in crontab. The wrappers load the ignored `data/config/ai26-localhost.env` file.

## 8. AI26 research settings

The canonical public methodology remains in:

- `configs/studies/ai26.example.yaml`
- `configs/studies/ai26.collection-codebook.yaml`
- `configs/studies/ai26.sources.example.toml`

The source design deliberately keeps a bounded, interpretable sample across acceleration/techno-optimist, x-risk/safety, Critical AI, labour/rights, anti-AI/pause, policy/parliamentary and frontier-lab discourse. These are sampling/sensitizing categories, not collection-time ideology labels.

RSS/blog/newsletter sources remain the priority for stable unattended collection. Firefox/browser-assisted capture covers platforms where API collection is unavailable, inappropriate or operationally fragile. YouTube should default to transcripts rather than media download unless the study explicitly needs multimodal material.

## 9. Smoke test

Use only public-safe/synthetic material when testing:

1. `laclaugpt-collect doctor --profile configs/ai26.localhost-remote.example.toml` succeeds.
2. `laclaugpt-collect distributed-check --study-config data/config/ai26.yaml` confirms configured remote services.
3. Start the Firefox backend and capture one public-safe page.
4. Run `run_ai26_localhost_sync.sh`; verify the canonical record in MongoDB has AI26 routing metadata.
5. Run `run_ai26_localhost_collect.sh`; verify at least one public RSS item is written or safely deduplicated.
6. Run `run_ai26_localhost_media.sh` against one small public-safe downloadable object.
7. Verify the object under the AI26 Allas/S3 project prefix and the corresponding checksum/object metadata in canonical state.
8. Repeat the sync/collection/media commands and confirm no duplicate canonical records or duplicate object identities are created.

## 10. Troubleshooting

Inspect logs under `data/logs/`. If a cron wrapper reports that another run is active, check `data/tmp/*.lock` and the running process before removing anything. Lock files themselves are harmless; `flock` ownership is what matters.

If MongoDB/Redis/Allas checks fail, first re-run `distributed-check` with the same sourced environment. Keep Redis authenticated and network-restricted. Do not expose the Firefox backend publicly.

If Firefox capture works locally but remote MongoDB is unchanged, run `run_ai26_localhost_sync.sh`; browser capture and remote synchronization are deliberately separated in the current architecture rather than making browser JavaScript perform storage work.
