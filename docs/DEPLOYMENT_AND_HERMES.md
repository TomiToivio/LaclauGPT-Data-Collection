# Deployment and Hermes operation

Collection uses one canonical implementation across machines. Machine, execution, browser and storage are independent configuration dimensions.

## Deployment matrix

| Scenario | machine | execution | browser | storage |
|---|---|---|---|---|
| Researcher laptop + Firefox | `laptop` | `cli` | `firefox-local` | local or distributed |
| Linux server, local storage | `linux-server` | `cron` or `systemd` | `none` | local |
| Linux server, distributed | `linux-server` | `cron` or `systemd` | `none` | distributed |
| Agent-operated variant | any | `agent` | configured browser mode | local or distributed |

See [`TWO_MACHINE_SETUP.md`](TWO_MACHINE_SETUP.md) for the two-role deployment pattern where a manually operated researcher host runs browser capture and a separate unattended cron host runs network collectors against the same shared run.

Checked-in examples include `configs/laptop.example.toml`, `configs/server-local.example.toml`, `configs/server.example.toml`, and the AI26 runtime examples. Real source lists, credentials, browser state and machine-specific settings remain below ignored `data/` or in external secret/configuration systems.

## Researcher laptop + Firefox

Use the laptop profile with the normal CLI. The browser capture backend binds to `127.0.0.1:8765` by default. Start the local capture backend only with an ignored study configuration and a private data root. The Firefox extension remains explicitly researcher-controlled.

Local persistence uses SQLite for canonical records/state, CSV/JSONL for interchange and the local filesystem below `data/` for captures, downloads, media and logs. Distributed deployments may instead use MongoDB/Redis/S3 while keeping the same canonical record identity.

## Linux server

A persistent Linux host may use local SQLite/filesystem storage or distributed MongoDB/Redis/S3 storage. Browser capture is `none` by default. Network collectors can be scheduled non-interactively.

Generate examples without installing anything:

```bash
laclaugpt-collect schedule cron --command-line "laclaugpt-collect doctor --profile data/config/server.toml"
laclaugpt-collect schedule systemd --command-line "laclaugpt-collect doctor --profile data/config/server.toml"
```

The cron example uses locking and appends logs below `data/logs/`. Systemd templates use restart-safe timer behavior. Actual operational commands and schedules belong in private deployment configuration.

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

### Hermes model

Current default Hermes model:

```text
deepseek-v4.1-flash:cloud
```

Hermes is expected to be capable. Reliability comes from explicit repository context, not from artificially reducing the model.

For cross-module workflows, the current default downstream analysis-model family is:

```text
gemma4:12b
gemma4:31b-cloud
gemma4:e2b
```

Collection/Hermes orchestration and downstream analytical inference are distinct roles. Do not silently substitute one model role for the other.

### AI26 configuration discovery

For AI26, Hermes and other agents must inspect these files before proposing or running collection:

```text
configs/studies/ai26.example.yaml
configs/studies/ai26.sources.example.toml
configs/studies/ai26.collection-codebook.yaml
```

Operational copies may exist under ignored `data/config/`. The public files are the methodological baseline. If a private runtime overlay cannot be read, use the public templates rather than inventing settings from model memory.

Historical LaclauGPT/CyborgAnthropology repositories may be searched only after current configuration has been checked, to recover missing public-safe source/codebook ideas or implementation patterns. Treat old runtime values as untrusted/private and never copy credentials or private target lists.

The example agent profile is `configs/hermes-ai26.example.toml`.

## Privacy and safety

Never commit real target/source lists, cookies, browser profiles, access tokens, MongoDB/Redis/S3 credentials, CSC project paths, raw captures or research exports. All runtime state remains under the private `data/` boundary or an external deployment/secret system.

Use an academic, professional and neutral tone in research-facing agent instructions. Repository agents should not assume a specific user's biography, ideology or informal persona.
