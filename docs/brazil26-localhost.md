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

The same checks are available as a non-destructive **dry-run** of the whole start.
`--dry-run` resolves the study config, data root, runtime env, Firefox command,
cron policy and source policy, prints one JSON plan, and exits **without**
starting a backend, launching Firefox or touching the crontab. It is safe on a
fresh checkout and returns 0 when a real start would proceed, 2 when it would
fail — so it doubles as a pre-collection gate:

```bash
laclaugpt-brazil26 --dry-run            # local profile plan
laclaugpt-brazil26 --dry-run --distributed   # also assert the Allas/Mongo + source policy
```

For backend-only work:

```bash
laclaugpt-brazil26 preflight --no-browser
```

## Start and stop

Normal daily start is one command. The wrapper sources the ignored runtime env,
resolves the same study/data precedence as the cron wrappers, and starts the
researcher session (loopback capture backend, session state under the Brazil26
data root, then the configured Firefox profile):

```bash
bash scripts/start_brazil26_localhost.sh            # one-command start
bash scripts/start_brazil26_localhost.sh --dry-run  # print the plan, start nothing
bash scripts/start_brazil26_localhost.sh --distributed  # require the Allas/Mongo preflight first
```

`laclaugpt-brazil26` (no subcommand) is the same start with the study and data
root taken from the environment. Stop from the same terminal with Ctrl-C, or
from another terminal with:

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

The public `configs/studies/brazil26.sources.example.toml` is a starting example
with bounded institutional sources, not an installed operational manifest. The
worker does not silently substitute it when the private manifest is missing.
Review the source selection, then create an ignored operational copy if these
sources match the study (the command preserves an existing file):

```bash
mkdir -p data/config
cp -n configs/studies/brazil26.sources.example.toml data/config/brazil26.sources.toml
```

Set `LACLAUGPT_SOURCE_MANIFEST` in the ignored runtime env file to that copy, or
to an existing approved manifest. Verify its active feed URLs before relying on
scheduled collection. An example URL is not evidence of a successful live feed
fetch. Until an operational manifest exists, RSS remains unconfigured.

Run the current localhost RSS worker with:

```bash
bash scripts/run_brazil26_localhost_collect.sh
```

The wrapper is lock-protected and project-scoped. It deliberately pins the RSS pass to local canonical storage (CSV/filesystem) and clears distributed backend selectors so a repo-root `.env` cannot silently turn this localhost job into a MongoDB/Redis/S3 run. Remote mirroring is a separate sync step.

To debug one source family, edit an ignored copy of `data/config/brazil26.sources.toml` so only the intended public-safe source is active, then run the same bounded worker. Do not create a second schema or scheduler.

Brazil26 does not inherit the AI26 realtime publication-date floor. Study-specific scheduling rules must be selected by project rather than reusing `RealtimePolicy.ai26()` globally.

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

With the local-first profile, objects remain local and the existing SQLite media index tracks completed files and retries. The **30-minute** cron entry invokes this same worker; it does not require MongoDB/S3 for the default filesystem profile. (Issue #233 supersedes the earlier 15-minute cadence: the installer now writes `*/30` and strips any stale `*/15` media entry.) Downstream local handoff should read the media index via `CollectionStore.media_states(source_url, collection_id="brazil26")`, rather than assuming the original append-only browser JSONL rows are rewritten in place. Configure distributed MongoDB/S3 only when the private runtime explicitly enables it.

The media cron entry is `*/30 * * * *` inside the marker-managed Brazil26 block (issue #233; it supersedes the earlier 15-minute cadence). An existing `data/config/brazil26-localhost.env` can provide `BRAZIL26_CONFIG` for direct installation and manual media runs; the launcher-pinned study config and data root take precedence. Verify the actual host installation and one scheduled tick on the research workstation. CI exercises only synthetic media, not authenticated platform downloads.

For each of Instagram, X and TikTok, capture a permitted public record containing a video reference, run the media worker, and inspect a completed or explicit failed/unsupported media-index entry. URL expiry, access restrictions and platform-specific signed URLs may prevent an individual video from downloading; do not interpret a synthetic test as proof of live platform coverage.

## Optional remote sync

The default localhost profile does not instantiate the distributed mirror. To opt in, configure one or more distributed backends in the ignored env file, for example MongoDB records, Redis configuration, or S3 objects. Then run:

```bash
laclaugpt-brazil26 check --study-config "$BRAZIL26_CONFIG"
```

The browser backend will mirror only when the effective settings request distributed infrastructure. Local capture remains the durable first hop.

### Distributed media to CSC Allas

The default `run_brazil26_localhost_media.sh` is deliberately local-first: it pins
`LACLAUGPT_OBJECT_BACKEND=filesystem` and clears the remote selectors so a repo-root
`.env` cannot switch it into the distributed plane. For the #233 deployment, where
queued videos must land in CSC Allas with their object key and state recorded in the
project-scoped MongoDB, use the distributed wrapper instead:

```bash
bash scripts/run_brazil26_localhost_media_distributed.sh
```

It sets `LACLAUGPT_RECORD_BACKEND=mongodb` and `LACLAUGPT_OBJECT_BACKEND=s3`
**unconditionally**, refuses to run without `LACLAUGPT_S3_BUCKET` /
`LACLAUGPT_MONGODB_URI` (fail closed, never a silent filesystem fallback), and
enforces the source policy before touching the network. Allas credentials come
from `allas-conf` / `~/.aws`, never from the env file.

An explicit conflicting setting is **refused**, not quietly overridden: if the
environment pins `LACLAUGPT_OBJECT_BACKEND=filesystem` or
`LACLAUGPT_RECORD_BACKEND=csv` (which the local-first wrapper legitimately does),
this wrapper exits 2 and names the variable. Running it on the local plane would
upload nothing while the cron still reported success, so the misconfiguration has
to surface.

Install **one** media cron entry per host, and pick the worker with the installer
rather than editing the crontab by hand:

```bash
LACLAUGPT_BRAZIL26_MEDIA_MODE=allas bash scripts/install_cron_brazil26.sh   # CSC Allas
LACLAUGPT_BRAZIL26_MEDIA_MODE=local bash scripts/install_cron_brazil26.sh   # local-first (default)
```

Switching mode removes the other mode's entry, because the two wrappers share one
lock and would otherwise fight over it.

### Source policy (X, Instagram and TikTok only)

The Brazil26 deployment collects X, Instagram and TikTok and nothing else. The
policy lives in the source manifest's `enabled_platforms`, and preflight asserts
it:

```bash
laclaugpt-brazil26 preflight --distributed   # also asserts Allas/Mongo config
```

A manifest that enables RSS, YouTube, Telegram, Reddit, Bluesky, Mastodon or
arXiv is refused by preflight and by the collect worker; the RSS pass is skipped
for a manifest that does not enable it. `configs/studies/brazil26.sources.example.toml`
declares `enabled_platforms = ["x", "instagram", "tiktok"]`; its institutional
RSS/YouTube rows are kept as provenance with `enabled = false`.

## Validate before Phase 1 analysis

Run:

```bash
laclaugpt-brazil26 validate --data-root ./data
```

Validation parses every normalized JSONL row, validates it against the canonical `CanonicalRecord` model, rejects an explicit non-Brazil `collection_id`, reports duplicate source URLs and returns non-zero when malformed rows are found.

A clean validation result is the handoff gate to LaclauGPT-Data-Analysis. The analysis stage should consume the canonical records without changing collection provenance.

## Smoke test

Use public-safe material:

1. `laclaugpt-brazil26 --dry-run` returns a plan with `status: ready` and exit 0, and starts nothing.
2. `laclaugpt-brazil26 preflight` returns `status: ok`.
3. Start with `bash scripts/start_brazil26_localhost.sh`.
4. `laclaugpt-brazil26 status` reports `running` and the Brazil study.
5. Capture one configured public page.
6. Confirm a canonical row appears under `data/normalized/`.
7. Run the bounded RSS worker once.
8. Run media processing if the captured record contains media.
9. Run `laclaugpt-brazil26 validate`.
10. Restart the session and confirm existing records are not duplicated by source identity.
11. Stop with Ctrl-C or `laclaugpt-brazil26 stop`.

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

If an older workstation cron block points at `.worktrees/brazil26-runtime`,
repair the runtime prerequisites before reinstalling it. From the canonical
checkout, create a checkout-local environment so the wrappers do not fall back
to an executable whose editable install still points at the stale worktree:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[feeds,browser,youtube,distributed]'
.venv/bin/python -c 'import laclaugpt_data_collection; print(laclaugpt_data_collection.__file__)'
```

The printed package path must be under this checkout's `src/`. This prepares
future scheduled workers; it does not migrate or restart an already-running
browser backend. Other environments that still import from the stale directory
must also be repointed before that directory can be retired.

Ensure the ignored runtime env file exists, `BRAZIL26_CONFIG` names the real
private study, and `LACLAUGPT_SOURCE_MANIFEST` names an existing operational
manifest as described above. Collect and sync resolve these values after loading
the env file. Explicit study and data paths passed by the installer take
precedence over values in the env file. Use absolute runtime paths when possible;
relative worker paths are based on the canonical checkout.

Run the collection and media wrappers manually first. Run sync as well when
remote mirroring is configured. A missing source manifest cannot be repaired by
repointing cron alone. Then install and inspect the marker-managed block:

```bash
bash scripts/install_cron_brazil26.sh
crontab -l | sed -n '/BEGIN LACLAUGPT BRAZIL26/,/END LACLAUGPT BRAZIL26/p'
```

The installer derives `ROOT` from its checkout and passes the selected runtime
env, study and data paths to all three workers. Media remains every 15 minutes.
Verify an actual scheduled tick and its output in `data/logs/` before retiring
anything. Do not remove the stale directory while any editable install, running
process or scheduled command still depends on it; preserve its local edits and
the canonical research data. The repository cannot change or verify an installed
workstation crontab remotely.

Shell scripts are committed with LF line endings via `.gitattributes` (`*.sh text eol=lf`). If a Windows/WSL checkout has CRLF-corrupted working files despite a clean Git status, restore the affected tracked scripts from Git or renormalize the checkout before repointing cron.

Never commit live Brazil26 targets, credentials, cookies, browser profiles, private endpoints, collected research data, or downloaded media.
