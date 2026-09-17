# Brazil26 Firefox browser collection

Brazil26 reuses the shared Firefox collector and the current distributed storage stack. The browser capture path is intentionally local: Firefox talks only to a backend bound to `127.0.0.1`. Canonical records are staged under a Brazil26-only data root and continuously mirrored to the configured remote MongoDB/Redis/CSC Allas backends. Media downloading is separate from browsing and is safe to run from cron.

The implementation is based on the previously working private `collector/firefox` collector and preserves its study-isolation rule: Brazil26 must have its own private study config, Firefox profile, data root, SQLite state, dedup/checkpoints, run identity and remote namespace. Do not share those with AI26.

## 1. Install

Requires Python 3.11+, Firefox and access to the private Brazil26 configuration. From a checkout:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e '.[distributed]'
```

Do not put the real Brazil26 study YAML or `.env` in the public repository. `configs/brazil26.env.example` lists the supported variable names using placeholders only. Copy those names into a private environment file outside Git and fill the values from the current private deployment configuration.

At minimum the runtime must configure `LACLAUGPT_PROJECT_ID=brazil26`, the private config directory, MongoDB, Redis, S3/Allas and the Brazil26 data root. The public collector uses the same `LACLAUGPT_*` names as the rest of the distributed Data Collection stack.

## 2. Create a dedicated Firefox profile

Open `about:profiles`, create a profile reserved for Brazil26 and launch it. Keeping Brazil26 separate prevents cookies, extension-local settings and operational state from being confused with AI26 or another study.

Install the extension temporarily for development/research use:

1. Open `about:debugging#/runtime/this-firefox`.
2. Choose **Load Temporary Add-on**.
3. Select `browser/firefox/manifest.json` from this repository.
4. Keep this Brazil26 Firefox profile dedicated to the study.

The extension uses the shared code in `browser/firefox/`. Do not fork a Brazil-specific copy unless the shared collector genuinely requires a compatibility fix.

## 3. Verify private configuration and remote services

Load your private environment, then run:

```bash
python -m laclaugpt_data_collection.brazil26_browser check \
  --study-config /path/to/private/brazil26.yaml
```

The command refuses a non-Brazil study config, enforces the `brazil26` project namespace and performs the distributed control-plane smoke check without printing credentials.

## 4. Start the localhost backend

```bash
python -m laclaugpt_data_collection.brazil26_browser backend \
  --study-config /path/to/private/brazil26.yaml \
  --host 127.0.0.1 \
  --port 8765 \
  --data-root /path/to/private/brazil26-data
```

The Brazil26 wrapper will not bind to a LAN/VPN address. It starts the existing shared `CaptureServer`, retains the proven local raw/canonical/state files as a recovery fallback, and mirrors new canonical JSONL rows to the configured distributed sink. An offset advances only after remote ingest succeeds, so a transient MongoDB/Redis/S3 failure is retried rather than silently dropping the record.

On startup it prints a sanitized readiness summary showing the study, project id, local backend URL and remote backend identities. Credentials are never printed.

## 5. Point Firefox at localhost and verify identity

Set the extension backend URL to the same loopback address and port, normally:

```text
http://127.0.0.1:8765
```

Before browsing, verify:

```bash
curl http://127.0.0.1:8765/status
curl http://127.0.0.1:8765/tour
```

`/status` must show the intended Brazil26 study identity. `/tour` shows the accounts/targets from the private study config and whether the configured study window is active. If the identity is wrong, stop the backend and correct the private config before collecting anything.

## 6. Normal capture workflow

Browse the configured public platform pages using the dedicated Brazil26 profile. The extension captures supported API responses and posts them to localhost. The backend normalizes them through the shared platform parsers.

During collection:

- local raw captures and canonical JSONL are written below the Brazil26 data root;
- canonical records are mirrored to the Brazil26 MongoDB namespace;
- lightweight coordination/handoff references are published through the configured Redis namespace;
- raw canonical payload objects are persisted through the configured S3/Allas backend;
- media URLs are recorded, but large media downloads do not block browser capture.

If the remote mirror temporarily fails, browser capture continues locally. The mirror retries from the last durable byte offset. Stop the backend with Ctrl-C; it performs one final mirror pass and writes a local manifest.

## 7. Media downloader as cron

Media is downloaded independently with the existing distributed media runner through the Brazil26 wrapper:

```bash
python -m laclaugpt_data_collection.brazil26_browser media \
  --study-config /path/to/private/brazil26.yaml \
  --data-root /path/to/private/brazil26-data \
  --workers 4 \
  --limit 100
```

The downloader uses the same Brazil26 MongoDB/Redis/S3 settings, durable local media index and deterministic media keys. Successful media is not redownloaded; failed jobs stay retryable. The command prints counts for scanned/queued/completed/failed records and returns non-zero when media failures remain.

Example crontab entry, using placeholders only:

```cron
*/15 * * * * cd /path/to/LaclauGPT-Data-Collection && /path/to/.venv/bin/python -m laclaugpt_data_collection.brazil26_browser media --study-config /path/to/private/brazil26.yaml --data-root /path/to/private/brazil26-data --workers 4 --limit 200 >> /path/to/private/logs/brazil26-media.log 2>&1
```

Keep the actual checkout path, config path, data path, endpoints and credentials private.

## 8. Minimal smoke test

1. Run the `check` command and require `status: ok`.
2. Start the backend on `127.0.0.1`.
3. Confirm `/status` reports the Brazil26 study.
4. Open one configured public target in the dedicated Firefox profile.
5. Confirm the backend capture counters increase.
6. Confirm a canonical row appears under `<data-root>/normalized/`.
7. Confirm the row appears in the Brazil26 remote MongoDB namespace and the Redis collected/handoff stream receives the corresponding lightweight reference.
8. Run the `media` command and verify any pending media is either completed, skipped as already complete, or left as an explicit retryable failure.

## 9. Troubleshooting

If Firefox cannot reach `/status` or `/tour`, first confirm the backend process is running on the same host/port configured in the extension. The backend intentionally rejects non-loopback bind addresses.

If capture works locally but remote mirroring fails, keep the backend running if safe to do so: local collection remains durable. Re-run the `check` command, inspect the private MongoDB/Redis/Allas environment, then restart the backend. The `.brazil26-distributed-offsets.json` file under the private data root is the mirror checkpoint; do not copy it to AI26.

If media fails, inspect the cron log and rerun the same command. Do not delete `state.sqlite3` merely to force retries because it contains deduplication, checkpoints and media status.

## Privacy and publication boundary

Never commit real Brazil26 account lists, study YAML, `.env`, credentials, hostnames, private ports, machine paths, raw captures, normalized research data, media, logs or state databases. Public code and docs should contain only reusable logic, synthetic fixtures and placeholders.
