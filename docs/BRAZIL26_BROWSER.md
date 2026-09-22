# Brazil26 Firefox browser collection

Brazil26 is a human-researcher workflow built on the shared LaclauGPT Firefox capture stack. For the complete one-researcher localhost workflow, including preflight/status/stop/validation, see [`brazil26-localhost.md`](brazil26-localhost.md). Operational study configuration remains private. The canonical study file is:

```text
<private-config-root>/brazil26/study.yaml
```

The public repository contains only reusable runtime code, synthetic tests and public-safe documentation.

## One-command researcher workflow

After installing the package and preparing the existing Brazil26 runtime environment, start a session with:

```bash
laclaugpt-brazil26
```

That command:

1. resolves the private Brazil26 study config;
2. refuses to fall back to the public example config when the private file is missing;
3. reuses the existing Brazil26 data root and durable SQLite/media/mirror state;
4. ensures the marker-managed Brazil26 cron block exists;
5. starts the localhost-only capture backend; distributed mirroring is enabled only when the effective runtime explicitly requests MongoDB/Redis/S3;
6. launches Firefox using the configured Brazil26 research profile;
7. keeps the process attached so Ctrl-C stops the local session cleanly.

By default the private repository is expected next to this checkout as
`<private-config-checkout>`. Override it with `LACLAUGPT_PRIVATE_REPO`, or set
`BRAZIL26_CONFIG` / `LACLAUGPT_STUDY_CONFIG` to the exact YAML path.

The existing data root is taken from `LACLAUGPT_DATA_ROOT`; when unset it
remains the repository `data/` tree used by the current Brazil26 scripts.
The launcher does not rename or migrate the active dataset.

## Runtime environment

The launcher reads `data/config/brazil26-localhost.env` when present and then
forces the study identity to `LACLAUGPT_PROJECT_ID=brazil26`. The public default
is local-only (`auto`/filesystem/memory/local), so MongoDB, Redis and CSC
Allas/S3 are not required. Distributed settings remain optional and must stay
in ignored/private runtime configuration.

Useful browser variables:

```bash
LACLAUGPT_FIREFOX_PROFILE="Brazil26 Research"
# or
LACLAUGPT_FIREFOX_PROFILE_PATH=/private/path/to/firefox/profile
# WSL or other non-standard installation:
LACLAUGPT_FIREFOX_COMMAND='powershell.exe ... firefox.exe'
```

If Firefox is not discoverable, startup fails clearly instead of opening an
uncontrolled browser profile.

For backend-only maintenance or debugging:

```bash
laclaugpt-brazil26 --no-browser
laclaugpt-brazil26 --no-cron
```

The existing low-level commands remain available for compatibility:

```bash
laclaugpt-brazil26 check --study-config /private/brazil-election-2026.yaml
laclaugpt-brazil26 backend --study-config /private/brazil-election-2026.yaml --data-root ./data
laclaugpt-brazil26 media --study-config /private/brazil-election-2026.yaml --data-root ./data
```

## Firefox extension

Use a dedicated Firefox profile for Brazil26. Install the shared extension from
`browser/firefox/manifest.json` as described in `browser/firefox/README.md`.
Do not fork Brazil-specific browser code unless the shared collector requires a
real compatibility change.

The capture backend binds to loopback only. Verify the live study identity with:

```bash
curl http://127.0.0.1:8765/status
curl http://127.0.0.1:8765/tour
```

The status must identify Brazil26 before collecting research material.

## TikTok and Instagram media

Browser capture records media references without blocking interactive research.
The Brazil26 media worker uses the existing persistent `MediaDownloader` and
distributed media runner. TikTok and Instagram image/video references supported
by the canonical media model are downloaded later to the configured storage.

Media identity includes the collection id, platform, source identity and media
index. Completed items are skipped on later runs. Failed items remain retryable.
Object keys are deterministic and study-scoped, so the same source URL can be
present in Brazil26 and another study without sharing download state.

The distributed media runner additionally filters loaded records to the active
project id. A Brazil26 run therefore refuses to process explicitly tagged AI26
records even when both accidentally exist below one local data root.

## Cron

The one-command launcher runs `scripts/install_cron_brazil26.sh` unless `--no-cron` is used. The installer
owns a marker-delimited block:

```text
# BEGIN LACLAUGPT BRAZIL26
...
# END LACLAUGPT BRAZIL26
```

Repeated installation replaces that block instead of adding duplicates. The
media job runs every 15 minutes, passes the resolved private Brazil26 config and
data root explicitly, and writes to:

```text
data/logs/brazil26-media.log
```

The shell wrapper uses `flock`, and the distributed media runner also uses its
per-data-root lock, so overlapping media runs exit safely.

Inspect the installed jobs with:

```bash
crontab -l
tail -f data/logs/brazil26-media.log
```

Remove the Brazil26 cron block by editing the crontab and deleting the lines
between the two Brazil26 markers. Re-running `laclaugpt-brazil26` reinstalls it.

## Continuing existing Brazil26 state

This workflow is deliberately additive. It keeps the existing local normalized
JSONL, SQLite/media index, mirror offset file and distributed Brazil26 namespace.
The mirror checkpoint advances only after successful remote ingest. Existing
records remain visible, new records append to the same logical study, completed
media remains recognized, and failed media can retry.

Brazil26 and AI26 must still use distinct Firefox profiles and project ids. The
runtime now also rejects a cross-study `collection_id` in the Brazil26 mirror,
providing a second guard against accidental dataset mixing.

## Stop and smoke-test

Stop an interactive session with Ctrl-C. The backend performs a final mirror pass
and writes its manifest before exit.

A local smoke test is:

1. run `laclaugpt-brazil26`;
2. confirm `/status` reports Brazil26;
3. browse one configured TikTok or Instagram target in the Brazil26 Firefox profile;
4. confirm a new canonical row appears under the existing data root;
5. confirm the row reaches the Brazil26 distributed namespace;
6. run the media worker or let cron process it;
7. confirm a completed media item is skipped on a second run.

Public CI does not require the private repository. Unit tests use synthetic paths,
fixtures and mocked browser/process behavior.

## Privacy boundary

Never commit the real Brazil26 study YAML, account lists, browser profiles,
cookies, credentials, hostnames, private endpoints, collected records, downloaded
media or researcher-specific settings to this public repository.
