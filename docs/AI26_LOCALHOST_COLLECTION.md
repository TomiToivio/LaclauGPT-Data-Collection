# AI26 localhost collection

This is the researcher-laptop profile for AI26. Firefox capture and ordinary CLI collection run locally, while canonical distributed state uses the same remote MongoDB, Redis configuration namespace and CSC Allas/S3 object storage as other AI26 workers.

The public AI26 files are methodology/templates only. Copy them under ignored `data/config/` before use. Do not commit endpoints, credentials, cookies, private target lists or browser profiles.

Choose an absolute checkout path locally and keep it out of the public repository. In commands below, replace `<absolute-repo-path>` at deployment time.

## 1. Install

```bash
cd <absolute-repo-path>
python -m venv .venv
source .venv/bin/activate
pip install -e '.[distributed,feeds,youtube,documents]'
mkdir -p data/config data/logs data/tmp
cp configs/studies/ai26.example.yaml data/config/ai26.yaml
cp configs/studies/ai26.sources.example.toml data/config/ai26.sources.toml
cp configs/studies/ai26.collection-codebook.yaml data/config/ai26.collection-codebook.yaml
cp .env.example data/config/ai26-localhost.env
```

Before doing anything else, verify both commands resolve to the required tree:

```bash
pwd
git rev-parse --show-toplevel
```

Both must resolve to the same local checkout. Do not commit that machine-specific path.

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
# Credentials are managed by CSC allas-conf in S3 mode (~/.aws/*).
# Do not duplicate Allas access/secret keys in this env file.
LACLAUGPT_S3_SIGNATURE_VERSION=s3
LACLAUGPT_S3_ADDRESSING_STYLE=auto
```

Configure CSC Allas first with `allas-conf` in S3 mode. boto3 then reads
the credential/config files under `~/.aws/`; this same file-based mechanism
works for cron without exporting credentials into the crontab or project env.

Load the project env for interactive commands:

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
cd <absolute-repo-path>
bash scripts/run_firefox_study.sh data/config/ai26.yaml data 8765
```

The backend binds to `127.0.0.1:8765` only. Keep that default.

In another terminal, verify the backend using the documented health endpoint/current browser-capture instructions in `docs/BROWSER_CAPTURE.md`.

## 4. Load the Firefox extension

Open Firefox and go to `about:debugging`, choose **This Firefox**, then **Load Temporary Add-on** and select `browser/firefox/manifest.json`.

Use the extension with the AI26 study/backend. Captures are persisted locally first. The distributed sync wrapper mirrors canonical records to the shared remote namespace without changing their canonical source identity.

Run a manual sync:

```bash
bash scripts/run_ai26_localhost_sync.sh
```

Re-running it is safe: the existing distributed sync/lease logic is responsible for deduplication.

## 5. Run non-browser collection

Use the single bounded localhost wrapper:

```bash
bash scripts/run_ai26_localhost_collect.sh
```

One invocation performs two canonical passes under the same lock and scheduler:

1. RSS/Atom through the mature `laclaugpt-server-rss` worker.
2. Executable plugins from the same source manifest: bounded Bluesky account collection and arXiv-backed scholarly queries.

Both passes use `project_id=ai26` and `collection_id=ai26`, write through the configured canonical record backend, and remain idempotent by canonical source identity. The plugin pass applies the study's `publication_date_floor` (currently `2026-09-01`). Missing publication timestamps are retained but explicitly marked unresolved, matching the public study policy.

Source-family labels, arena, priority and machine identity are sampling/collection provenance only. They are not ideology ground truth and must not become Laclaudian or ideological classifications during Collection.

X remains browser-assisted and manual. Firefox itself is never scheduled. Mastodon account rows are not guessed through the current public-timeline-only plugin, and YouTube channel-name rows are not converted into invented video URLs. Those source families should join this same wrapper once their canonical target-specific execution path can consume the manifest safely. Do not create a second scheduler or study-specific schema to add them.

### Distributed queue mode (#378)

The same collector can take its work from the shared MongoDB queue instead of re-reading the
manifest on every tick. This is the localhost half of the three-host deployment: the queue, not a
CLI flag, decides who may take which job.

```bash
# claim non-browser jobs for this host and settle each one
python -m laclaugpt_data_collection.ai26_localhost_collect \
    --source-manifest "$LACLAUGPT_SOURCE_MANIFEST" \
    --study-config "$LACLAUGPT_STUDY_CONFIG" \
    --dispatch-mongo --worker-id "desktop-$(hostname -s)" --max-jobs 10

# read-only health: capabilities, queue depth by status/kind, browser backlog
python -m laclaugpt_data_collection.ai26_localhost_collect --status
```

What the worker declares matters. The CLI collector declares **only** `non_browser`, because it
cannot drive Firefox; the queue filters browser kinds out inside the Mongo query, so a browser job
cannot be handed over even if the worker asks. The Laskin worker keeps the same restriction. When
the capability is missing from the queue entry, the job is not lost: it stays pending and appears
in `--status` as `browser_backlog`, which is what the X capture session is working down.

Browser work therefore stays human-driven by design (#258): start the capture backend with
`scripts/start_ai26_x_capture.sh`, browse in Firefox, and let the extension post to the loopback
capture server. Nothing here schedules Firefox or automates a session.

`--status` needs `LACLAUGPT_MONGODB_URI` from the private runtime env. Without it the command exits
2 with `no MongoDB URI in the runtime settings` rather than pretending the queue is empty; that is
also how a host with no AI26 runtime configuration is detected.

### This workstation's live setup (#378)

Brazil26 collection is complete and retired here; the same 8765 port now serves AI26 so the
already-loaded Firefox extension needs no reconfiguration.

```sh
systemctl --user status ai26-capture.service    # owns 127.0.0.1:8765
systemctl --user status brazil26-capture.service  # disabled
curl -s http://127.0.0.1:8765/status             # study: ai26
```

- **Data root:** `data/ai26/` — its own `state.sqlite3`, `raw/`, `normalized/`, `media/`.
  Sharing `data/` would dedupe AI26 posts against Brazil26's `seen_posts`, which is keyed by
  `(platform, document_id)` with no project scope, so a post Brazil26 saw first would be
  skipped for AI26.
- **Profile:** local-only (no MongoDB/Redis/S3); the backend reports
  `remote: {status: disabled}` and writes canonical JSONL locally. `--status` on the queue
  worker exits 2 without a Mongo URI rather than reporting an empty queue.
- **Credentials in raw captures:** the extension posts every X GraphQL response, including
  token-bearing ones. `CollectionStore.append_raw` redacts credential-keyed fields and bare
  JWTs before writing, so `raw/` stays safe to keep; the redaction is structural, keys and
  list lengths survive for debugging.
- **Publication floor:** browser capture stores what the timeline shows, including posts
  older than `publication_date_floor`; the plugin pass applies the floor. Filter downstream
  rather than assuming capture is windowed.
- **Media:** inline capture produced none on this host; run `scripts/run_ai26_localhost_media.sh`
  once an object store is configured.

### Config fingerprint and queue smoke check (#392)

AC 1 of #378 needs proof that two hosts resolve the same study settings. Compare a hash, not
two private YAMLs:

```sh
PYTHONPATH=src python -m laclaugpt_data_collection.effective_config \
    --project "$LACLAUGPT_STUDY_CONFIG" --hash-only
```

This workstation resolves the private AI26 study to
`sha256:a17af4cb84fefefdfc338a10c900dd1e9c0656ffd59486908dfa0af64f56af9d`. Run the same
command on the other two hosts; only these hashes have to match, and the snapshot output
(`--hash-only` omitted) redacts credentials and private target lists.

The queue path can be exercised without the shared database, against the loopback `mongod`
(a smoke database, not the study store):

```sh
LACLAUGPT_MONGODB_URI=mongodb://127.0.0.1:27017 \
LACLAUGPT_MONGODB_DATABASE=laclaugpt_smoke LACLAUGPT_PROJECT_ID=ai26 \
PYTHONPATH=src python -m laclaugpt_data_collection.ai26_localhost_collect --status
```

It reports `capabilities: [non_browser]`, `browser_capable: false` and `browser_backlog: 0`,
which is the capability split this host is supposed to have. The shared deployment still
needs the real URI in the private env file.

**Publication floor — decision (#392).** Browser capture keeps posts older than
`publication_date_floor` on purpose: the capture is evidence of what the timeline showed, and
the study's window is applied when records are selected for analysis (the plugin pass already
does this). Filtering at capture would silently discard the raw provenance that makes a
sampling audit possible. The 323 pre-floor posts from the first pass therefore stay.

## 6. Download media/files and upload to Allas

```bash
bash scripts/run_ai26_localhost_media.sh
```

The existing distributed media worker scans locally captured canonical records, downloads pending media, stores deterministic objects in CSC Allas/S3, persists checksums/status in downloader state, and refreshes affected canonical records in MongoDB.

## 7. Cron

All wrappers use `flock`, so overlapping invocations exit cleanly instead of double-running. They also prepend the repository `.venv/bin` and the user's `~/.local/bin` to `PATH`, because cron normally starts with a minimal environment.

Install entries using your local absolute checkout path; keep the real path only in the local crontab:

```cron
10 * * * * cd <absolute-repo-path> && bash scripts/run_ai26_localhost_sync.sh >> data/logs/ai26-sync.log 2>&1
17 * * * * cd <absolute-repo-path> && bash scripts/run_ai26_localhost_collect.sh >> data/logs/ai26-collect.log 2>&1
27 * * * * cd <absolute-repo-path> && bash scripts/run_ai26_localhost_media.sh >> data/logs/ai26-media.log 2>&1
```

Do not put secrets directly in crontab. The wrappers load the ignored `data/config/ai26-localhost.env` file.

Firefox itself is manual and must not be added to cron.

After installing the crontab, verify the placeholder was replaced locally:

```bash
crontab -l | grep -F '/path/to/' && echo 'ERROR: placeholder cron path remains' || true
```

## 8. AI26 research settings

The canonical public methodology remains in:

- `configs/studies/ai26.example.yaml`
- `configs/studies/ai26.collection-codebook.yaml`
- `configs/studies/ai26.sources.example.toml`

The source design deliberately keeps a bounded, interpretable sample across acceleration/techno-optimist, x-risk/safety, Critical AI, labour/rights, anti-AI/pause, policy/parliamentary and frontier-lab discourse. These are sampling/sensitizing categories, not collection-time ideology labels.

RSS/blog/newsletter sources remain the priority for stable unattended collection. Firefox/browser-assisted capture covers platforms where API collection is unavailable, inappropriate or operationally fragile. YouTube should default to transcripts rather than media download unless the study explicitly needs multimodal material.

Keep the ignored runtime copies synchronized with the public templates when the public source design changes. In particular, compare `data/config/ai26.sources.toml` against `configs/studies/ai26.sources.example.toml` before an unattended run so newly audited sources are not silently omitted.

## 9. Smoke test

Use only public-safe/synthetic material when testing:

1. `laclaugpt-collect doctor --profile configs/ai26.localhost-remote.example.toml` succeeds.
2. `laclaugpt-collect distributed-check --study-config data/config/ai26.yaml` confirms configured remote services.
3. Start the Firefox backend and capture one public-safe page.
4. Run `bash scripts/run_ai26_localhost_sync.sh`; verify the canonical record in MongoDB has AI26 routing metadata.
5. Run `bash scripts/run_ai26_localhost_collect.sh`; verify at least one public RSS, Bluesky or arXiv item is written or safely deduplicated in the same AI26 namespace.
6. Run `bash scripts/run_ai26_localhost_media.sh` against one small public-safe downloadable object.
7. Verify the object under the AI26 Allas/S3 project prefix and the corresponding checksum/object metadata in canonical state.
8. Repeat the sync/collection/media commands and confirm no duplicate canonical records or duplicate object identities are created.
9. Repeat a wrapper with a cron-like `PATH=/usr/bin:/bin`; it must still find the repository virtualenv command.
10. Run `python tools/verify_contracts.py`.

## 10. Troubleshooting

Inspect logs under `data/logs/`. If a cron wrapper reports that another run is active, check `data/tmp/*.lock` and the running process before removing anything. Lock files themselves are harmless; `flock` ownership is what matters.

If MongoDB/Redis/Allas checks fail, first re-run `distributed-check` with the same sourced environment. Keep Redis authenticated and network-restricted. Do not expose the Firefox backend publicly.

If Firefox capture works locally but remote MongoDB is unchanged, run `bash scripts/run_ai26_localhost_sync.sh`; browser capture and remote synchronization are deliberately separated in the current architecture rather than making browser JavaScript perform storage work.

If a collect wrapper reports a missing runtime env, study config or source manifest, check which checkout is running it. The private configuration is read from `$LACLAUGPT_RUNTIME_CONFIG_ROOT/data/config/` (default: the checkout the wrapper lives in), and `data/` is untracked, so a wrapper run from a linked Git worktree (`.worktrees/<name>/`) can never find its own copy. The wrapper says whether the file exists in the main checkout and refuses either way: point it at the checkout that owns the private configuration with

```bash
LACLAUGPT_RUNTIME_CONFIG_ROOT=<main-checkout>
```

rather than copying the files into the worktree. A genuinely absent manifest or study config stays a hard stop — the wrapper never generates, copies or borrows one.
