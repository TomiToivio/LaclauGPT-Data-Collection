# LaclauGPT Data Collection agent skill

Operate Collection through the same canonical APIs used by the CLI. Never create a separate agent-only collector path.

## Scope

Collection owns source/browser/network capture, normalization, canonical source identity, provenance, collection state, raw/media persistence, scheduling and storage adapters. Analysis and Visualization are downstream modules.

## Canonical identity

`source_url` or a stable URI-like identifier is the semantic identity. Platform IDs remain aliases. Mongo `_id`, SQLite keys, filenames and queue IDs never replace `source_url`.

## Deployment modes

Laptop researcher workflow: `machine=laptop`, `execution=cli`, `browser=firefox-local`, local SQLite/filesystem/memory storage. Firefox capture binds to localhost and remains user controlled.

Linux server workflow: `machine=linux-server`, normally `execution=cron` or `systemd`, with `browser=none` unless a worker is explicitly configured. Storage may be local or distributed.

Local storage uses SQLite plus CSV/JSONL/Pandas-compatible files and the repository-local private `data/` filesystem. Distributed storage uses MongoDB for canonical records, Redis for coordination/settings/task queues/messaging, and S3-compatible storage such as CSC Allas for files and large blobs.

CSV/JSONL remains the manual handoff fallback.

## Privacy

All operational source lists, cookies, browser state, credentials, private configs, logs, data, downloads and run state belong below ignored `data/` or external secret/configuration management. Never print or return credentials from an agent tool.

## Hermes operations

Use `laclaugpt_data_collection.integrations.hermes` to inspect redacted configuration, validate environment, plan dry runs, inspect browser readiness and distributed queue capability, and stamp agent-triggered canonical records with caller provenance such as `hermes-agent`.

Dry-run and inspection paths must not contact external websites, Firefox, MongoDB, Redis, S3 or CSC infrastructure.

## Scheduling

Use generated cron/systemd examples rather than writing directly into system configuration. Scheduled execution should use lock/state under `data/runs/` and logs under `data/logs/` to reduce overlapping runs and support restart-safe operation.

## Pipeline handoff

On one machine, Analysis may consume the configured Collection `data/` root directly. In distributed operation, handoff occurs through canonical MongoDB records plus Redis coordination and S3/Allas object references. Do not make sibling repositories mandatory Python imports.

## Human and agent parity

An agent changes the caller/execution metadata, not the scientific meaning of the record. The same collectors, canonical schemas, storage adapters and privacy checks apply to human CLI, cron/systemd and agent operation.
