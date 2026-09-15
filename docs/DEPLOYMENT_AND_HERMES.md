# Deployment and Hermes operation

Collection uses one canonical implementation across machines. Machine, execution, browser and storage are independent configuration dimensions.

## Deployment matrix

| Scenario | machine | execution | browser | storage |
|---|---|---|---|---|
| Researcher laptop + Firefox | `laptop` | `cli` | `firefox-local` | local |
| Linux server, local storage | `linux-server` | `cron` or `systemd` | `none` | local |
| Linux server, distributed | `linux-server` | `cron` or `systemd` | `none` | distributed |
| Agent-operated variant | any | `agent` | configured browser mode | local or distributed |

Checked-in examples are `configs/laptop.example.toml`, `configs/server-local.example.toml` and `configs/server.example.toml`. Real source lists, credentials, browser state and machine-specific settings remain below ignored `data/` or in external secret/configuration systems.

## Researcher laptop + Firefox

Use the laptop profile with the normal CLI. The browser capture backend binds to `127.0.0.1:8765` by default. Start the local capture backend only with an ignored study configuration and a private data root. The Firefox extension remains explicitly researcher-controlled.

Local persistence uses SQLite for canonical records/state, CSV/JSONL for interchange and the local filesystem below `data/` for captures, downloads, media and logs. No MongoDB, Redis or S3 service is required.

## Linux server

A persistent Linux host such as a Pouta VM may use local SQLite/filesystem storage or distributed MongoDB/Redis/S3 storage. Browser capture is `none` by default. Network collectors can be scheduled non-interactively.

Generate examples without installing anything:

```bash
laclaugpt-collect schedule cron --command-line "laclaugpt-collect doctor --profile data/config/server.toml"
laclaugpt-collect schedule systemd --command-line "laclaugpt-collect doctor --profile data/config/server.toml"
```

The cron example uses `flock` with `data/runs/collection.lock` and appends logs to `data/logs/collection.log`. Systemd templates use `Persistent=true`, allowing missed timer runs to resume after downtime. Actual operational commands and schedules belong in private deployment configuration.

## Storage topologies

Local/simple:

```text
collectors -> canonical records -> SQLite
                       |-> CSV / JSONL
                       `-> data/files, data/media, data/downloads
```

Distributed:

```text
collectors -> MongoDB canonical records
          -> Redis coordination / settings / queues / messaging
          -> S3-compatible objects, e.g. CSC Allas
```

Redis is infrastructure, never a canonical research schema. Mongo `_id` does not replace `source_url`. S3 object references do not change record semantics. CSV/JSONL remains the manual transfer fallback.

When Analysis runs on the same machine, configure it to read this Collection module's `data/` root directly rather than hard-coding a sibling path.

## Hermes

The reusable integration surface is `laclaugpt_data_collection.integrations.hermes`. It can inspect a redacted effective configuration, validate a profile offline, create a dry-run plan, validate Firefox-local binding, describe distributed queue capability and stamp agent-triggered records with `caller=hermes-agent` provenance.

The corresponding skill is `skills/laclaugpt-data-collection/SKILL.md`.

Hermes uses the same Settings, canonical record and storage/deployment primitives as human CLI operation. Agent execution is an execution mode, not a second collector implementation.

## Privacy and safety

Never commit real target/source lists, cookies, browser profiles, access tokens, MongoDB/Redis/S3 credentials, CSC project paths, raw captures or research exports. All runtime state remains under the private `data/` boundary or an external deployment/secret system.
