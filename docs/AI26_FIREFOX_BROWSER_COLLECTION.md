# AI26 Firefox browser collection

AI26 uses the shared LaclauGPT Firefox collector with a localhost-only capture backend and the distributed AI26 storage stack. Firefox remains interactive on the research workstation; structured records are mirrored to the configured remote MongoDB, coordination uses Redis, and raw/media objects use CSC Allas/S3. Media downloading is independent from browser capture and is intended to run from cron.

Operational configuration is private. The canonical private location is `<private-config-root>/ai26/`. Do not copy real credentials, endpoints, machine paths, account lists, study targets, raw captures or `.env` files into this public repository.

## 1. Install

Requirements: Python 3.11+, Firefox, Git and access to the private AI26 configuration.

```bash
git clone https://github.com/TomiToivio/LaclauGPT-Data-Collection.git
cd LaclauGPT-Data-Collection
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e '.[distributed]'
```

On Windows/WSL, run the Python backend in the environment that can receive requests from the Firefox instance you use. The backend itself must bind only to loopback.

## 2. Load private AI26 configuration

Use the private configuration under `<private-config-root>/ai26/` as the source of truth. `configs/ai26.browser.env.example` contains only public-safe variable names and placeholders.

The runtime accepts the historical convention:

```bash
export AI26_CONFIG=/path/to/<private-config-root>/ai26/ai26.private.yaml
export AI26_MONGO_DATABASE=laclaugpt
```

Also configure the normal `LACLAUGPT_*` distributed variables for MongoDB, Redis and Allas/S3 from private configuration. At minimum use `LACLAUGPT_PROJECT_ID=ai26`, an AI26-only data root, MongoDB URI/database, Redis URL/key prefix and Allas/S3 endpoint/bucket/credentials.

Never put the populated environment file in the public checkout.

## 3. Create a dedicated Firefox profile

Open `about:profiles`, create a profile reserved for AI26 and launch it. AI26 must not share the Firefox profile, local data root, SQLite state, mirror checkpoint or operational config with Brazil26.

Install the extension:

1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on**.
3. Select `browser/firefox/manifest.json`.
4. Keep this profile dedicated to AI26 collection.

The extension implementation is shared. Do not maintain an AI26-specific fork of the extension unless a real compatibility difference requires it.

## 4. Check identity and remote services

Before collecting:

```bash
python -m laclaugpt_data_collection.ai26_browser check
```

or explicitly:

```bash
python -m laclaugpt_data_collection.ai26_browser check \
  --study-config /path/to/private/ai26.yaml
```

The check refuses a non-AI26 study configuration, requires the AI26 project namespace and performs the distributed storage smoke check without printing credentials.

## 5. Start the localhost backend

```bash
python -m laclaugpt_data_collection.ai26_browser backend \
  --data-root /path/to/private/ai26-data \
  --host 127.0.0.1 \
  --port 8766
```

`--study-config` can be omitted when `AI26_CONFIG` is set.

The command rejects non-loopback bind addresses. It starts the shared capture server, preserves local raw/canonical/state files as a recovery layer, and mirrors new canonical JSONL rows into the distributed AI26 sink. Mirror offsets advance only after successful remote ingest, so temporary remote failures do not silently drop captured records.

On startup the command prints a sanitized readiness summary including study identity, project id, local backend URL and remote backend status.

## 6. Point Firefox at the backend

Configure the extension backend URL to:

```text
http://127.0.0.1:8766
```

Before browsing, verify:

```bash
curl http://127.0.0.1:8766/status
curl http://127.0.0.1:8766/tour
```

`/status` must identify the intended AI26 study. `/tour` exposes the configured collection targets/window without changing them. If the study identity is wrong, stop collection and fix the private config first.

## 7. Browser collection behavior

Browse configured public sources with the dedicated AI26 Firefox profile. Supported API/network responses are sent to localhost and normalized by the shared platform parsers.

During collection:

- raw capture and canonical JSONL are written below the AI26-only data root;
- canonical records are mirrored to the AI26 MongoDB namespace;
- coordination/handoff references use the configured Redis namespace;
- raw/canonical payload objects use the configured Allas/S3 backend;
- media URLs are queued but large media downloads do not block interactive browsing.

If a remote service fails temporarily, local capture continues. Restarting the backend resumes mirroring from `.ai26-distributed-offsets.json`.

## 8. Media/video downloader cron job

Run media independently:

```bash
python -m laclaugpt_data_collection.ai26_browser media \
  --data-root /path/to/private/ai26-data \
  --workers 4 \
  --limit 200
```

The command uses the same private MongoDB/Redis/Allas settings, the AI26 namespace and a per-data-root lock. A second overlapping invocation is rejected rather than racing the active job. Completed media is tracked in the durable local media index and uses deterministic object keys/checksums, so repeated runs remain idempotent.

Example crontab, placeholders only:

```cron
*/15 * * * * cd /path/to/LaclauGPT-Data-Collection && /path/to/.venv/bin/python -m laclaugpt_data_collection.ai26_browser media --data-root /path/to/private/ai26-data --workers 4 --limit 200 >> /path/to/private/logs/ai26-media.log 2>&1
```

The output reports records scanned, queued, attempted, completed, failed, skipped and MongoDB refresh count. Download failures return a non-zero status and remain retryable. If a previous process crashed and left `.distributed-media.lock`, verify no downloader is running before removing that stale lock manually.

## 9. End-to-end smoke test

1. Run `ai26_browser check` and require `status: ok`.
2. Start the backend on `127.0.0.1:8766`.
3. Confirm `/status` reports AI26.
4. Open one configured public source in the AI26 Firefox profile.
5. Confirm capture counters increase.
6. Confirm a canonical row appears under `<data-root>/normalized/`.
7. Confirm the row reaches the configured AI26 MongoDB namespace and Redis handoff/control plane.
8. Confirm raw/object output appears under the configured AI26 Allas/S3 prefix.
9. Run the media command and verify pending media is completed, skipped as already complete, or left as an explicit retryable failure.

## 10. Isolation contract

AI26 and Brazil26 share reusable collector code only. Keep distinct:

- private study YAML/config;
- Firefox profile;
- local data/state root;
- SQLite dedup/media state;
- mirror checkpoint file;
- run IDs/manifests;
- Mongo/Redis namespace;
- S3/Allas project prefix;
- explicit `study` and `collection_id` provenance.

The AI26 mirror rejects canonical rows carrying another collection id, which prevents an accidentally shared local normalized directory from contaminating AI26 remote storage.

## 11. Troubleshooting

If Firefox cannot reach the backend, confirm the process is running and the extension points to the same loopback host/port. Non-loopback backend addresses are intentionally rejected.

If local capture succeeds but distributed mirroring fails, keep the local data root intact. Re-run `check`, verify the private Mongo/Redis/Allas environment and restart the backend. Do not copy Brazil26 checkpoint/state files into AI26.

If media fails, inspect the cron log and rerun the same command. Do not delete the AI26 SQLite state merely to force retries because it contains deduplication and media status.
