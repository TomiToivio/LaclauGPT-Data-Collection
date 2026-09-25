# Brazil26 localhost researcher runbook

This is the simplest supported Brazil26 workflow for one human researcher on one computer. It is **local-first**: Firefox capture, canonical JSONL, SQLite/index state, logs and downloaded files can run without MongoDB, Redis or CSC Allas. Remote services are optional.

Operational target lists and the real study configuration remain private. The expected private study file is:

```text
<private-config-root>/brazil26/study.yaml
```

## First-time setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,feeds,browser]'
bash scripts/install_brazil26.sh
cp configs/brazil26.env.example data/config/brazil26-localhost.env
```

Edit only the ignored `data/config/brazil26-localhost.env`. Set `BRAZIL26_CONFIG` to the real private YAML and configure a dedicated Firefox profile. Keep `LACLAUGPT_PROJECT_ID=brazil26`.

The public `configs/brazil26.localhost.example.toml` documents the local topology. The older `brazil26.localhost-remote.example.toml` is only for an explicitly distributed deployment.

## Preflight

Run this before collection:

```bash
set -a
source data/config/brazil26-localhost.env
set +a
laclaugpt-brazil26 preflight
```

Preflight checks the Brazil study identity, writable data directory, browser extension manifest, Firefox command/profile and study separation. Missing MongoDB/Redis/S3 is **not** an error in the default local profile.

For backend-only work:

```bash
laclaugpt-brazil26 preflight --no-browser
```

## Start and stop

Normal daily start is one command:

```bash
laclaugpt-brazil26
```

It starts the loopback capture backend, records session state under the Brazil26 data root and launches the configured Firefox profile. Stop from the same terminal with Ctrl-C, or from another terminal with:

```bash
laclaugpt-brazil26 stop --data-root ./data
```

The launcher terminates the backend cleanly and removes the session file.

Inspect status at any time:

```bash
laclaugpt-brazil26 status --data-root ./data
```

The command reports whether the backend is live, the active study returned by `/status`, the session metadata, and local normalized-file/row counts.

## Firefox setup

Use a dedicated Brazil26 Firefox profile. In Firefox:

1. Open `about:debugging`.
2. Choose **This Firefox**.
3. Choose **Load Temporary Add-on**.
4. Select `browser/firefox/manifest.json`.
5. Start `laclaugpt-brazil26`.
6. Verify `laclaugpt-brazil26 status` reports a Brazil study before capturing.

Do not reuse an AI26 research profile for Brazil26. The runtime also forces `LACLAUGPT_PROJECT_ID=brazil26` and rejects explicitly cross-study rows during remote mirroring.

## Local data and restart behaviour

Collection state remains below `LACLAUGPT_DATA_ROOT` (default `./data`). The browser backend persists raw capture, canonical normalized JSONL and its durable seen/index state. Re-running the researcher session resumes the same data root rather than creating an uncontrolled duplicate dataset.

Canonical source identity remains URL/stable-URI based, following the repository-wide deduplication contract.

Useful locations include:

```text
data/normalized/              canonical JSONL
data/raw/                     raw browser captures where applicable
data/database/                durable local indexes/state
data/media/ and data/files/   local downloaded objects
data/logs/                    worker logs
data/config/                  ignored runtime configuration
```

## Non-browser collection

The public Brazil26 source manifest includes bounded institutional sources. Run the current localhost RSS worker with:

```bash
bash scripts/run_brazil26_localhost_collect.sh
```

The wrapper is lock-protected and project-scoped. To debug one source family, edit an ignored copy of `data/config/brazil26.sources.toml` so only the intended public-safe source is active, then run the same bounded worker. Do not create a second schema or scheduler.

## Media/download processing

Process pending media with:

```bash
laclaugpt-brazil26 media \
  --study-config "$BRAZIL26_CONFIG" \
  --data-root ./data
```

or use the existing lock-protected wrapper:

```bash
bash scripts/run_brazil26_localhost_media.sh
```

With the local-first profile, objects remain local and the existing SQLite media index tracks completed files and retries. The 15-minute cron entry invokes this same worker; it does not require MongoDB/S3 for the default filesystem profile. Downstream local handoff should read the media index via `CollectionStore.media_states(source_url, collection_id="brazil26")`, rather than assuming the original append-only browser JSONL rows are rewritten in place. Configure distributed MongoDB/S3 only when the private runtime explicitly enables it.

The media cron entry is `*/15 * * * *` inside the marker-managed Brazil26 block. An existing `data/config/brazil26-localhost.env` can provide `BRAZIL26_CONFIG` for direct installation and manual media runs; the launcher-pinned study config and data root take precedence. Verify the actual host installation and one scheduled tick on the research workstation. CI exercises only synthetic media, not authenticated platform downloads.

For each of Instagram, X and TikTok, capture a permitted public record containing a video reference, run the media worker, and inspect a completed or explicit failed/unsupported media-index entry. URL expiry, access restrictions and platform-specific signed URLs may prevent an individual video from downloading; do not interpret a synthetic test as proof of live platform coverage.

## Optional remote sync

The default localhost profile does not instantiate the distributed mirror. To opt in, configure one or more distributed backends in the ignored env file, for example MongoDB records, Redis configuration, or S3 objects. Then run:

```bash
laclaugpt-brazil26 check --study-config "$BRAZIL26_CONFIG"
```

The browser backend will mirror only when the effective settings request distributed infrastructure. Local capture remains the durable first hop.

## Validate before Phase 1 analysis

Run:

```bash
laclaugpt-brazil26 validate --data-root ./data
```

Validation parses every normalized JSONL row, validates it against the canonical `CanonicalRecord` model, rejects an explicit non-Brazil `collection_id`, reports duplicate source URLs and returns non-zero when malformed rows are found.

A clean validation result is the handoff gate to LaclauGPT-Data-Analysis. The analysis stage should consume the canonical records without changing collection provenance.

## Smoke test

Use public-safe material:

1. `laclaugpt-brazil26 preflight` returns `status: ok`.
2. Start `laclaugpt-brazil26`.
3. `laclaugpt-brazil26 status` reports `running` and the Brazil study.
4. Capture one configured public page.
5. Confirm a canonical row appears under `data/normalized/`.
6. Run the bounded RSS worker once.
7. Run media processing if the captured record contains media.
8. Run `laclaugpt-brazil26 validate`.
9. Restart the session and confirm existing records are not duplicated by source identity.
10. Stop with Ctrl-C or `laclaugpt-brazil26 stop`.

## Troubleshooting

If preflight cannot find Firefox, set `LACLAUGPT_FIREFOX_COMMAND`, `LACLAUGPT_FIREFOX_PROFILE`, or `LACLAUGPT_FIREFOX_PROFILE_PATH` in the ignored env file.

For Windows Firefox launched from WSL, quote the complete command inside the shell-sourceable ignored env file, preserving the executable's spaces, for example:

```bash
LACLAUGPT_FIREFOX_COMMAND="'/mnt/c/Program Files/Mozilla Firefox/firefox.exe'"
```

Do not put an unquoted spaced path in an env file sourced by Bash. Preflight probes the executable with `--version` and reports a dead Linux snap launcher instead of treating its mere presence on PATH as browser readiness. This probe does not establish that the Firefox extension is installed or that platform capture has worked; verify those in a human-operated session.

If status says `stopped`, start the researcher session and verify no other service is occupying the configured loopback port.

If validation reports a cross-study `collection_id`, do not hand the dataset to analysis. Locate the originating capture/configuration first.

If a worker reports an existing lock, inspect the running process before deleting anything. Lock files themselves are harmless.

Never commit live Brazil26 targets, credentials, cookies, browser profiles, private endpoints, collected research data, or downloaded media.
