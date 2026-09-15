# Agent and Contributor Rules

This repository is public-safe infrastructure. Treat every commit as publishable.

This file is the canonical shared contract. Agent-specific files such as `CLAUDE.md`, `HERMES.md`, and `CODEX.md` may add workflow guidance but must not override this file, `docs/PRIVACY.md`, `docs/RUNTIME_DATA.md`, or CI.

## Scope

Keep this repository limited to data collection: source/browser/network capture, platform parsers, normalization, provenance, collection state, media/raw persistence, scheduling, and storage adapters. Analysis, dashboards, simulations and other module responsibilities belong elsewhere.

## Canonical record contract

All collectors and storage adapters MUST use the project-wide canonical LaclauGPT record contract.

- `source_url` or a stable URI-like equivalent is the semantic source identity.
- Canonicalize source identity deterministically before persistence.
- Platform-native IDs belong in `source_native_ids`; they never replace `source_url`.
- Mongo `_id`, SQLite integer keys, CSV row numbers and local filenames are backend details, not research identities.
- Collection populates `source`, source-side `content`, media/file references and collection provenance. Analysis enriches the same record later.
- Text-only records are valid. Do not invent multimodal fields.
- Flat legacy fields are accepted only through bounded adapters. Persisted canonical records use structured sections.
- Every persisted schema change requires an explicit schema-version decision, migration note and synthetic round-trip contract tests.
- CSV/JSONL/SQLite/Mongo representations must reconstruct the same logical record.

`NormalizedRecord` is a compatibility constructor for existing collectors, not a second persistent schema.

## Mandatory runtime data boundary

All runtime and study-specific material belongs below `data/`, and the complete `data/` tree stays outside Git. Follow `docs/RUNTIME_DATA.md`.

Logs, databases, local configuration, CSV/JSONL files, codebooks, source/target lists, downloads, media, browser state, transcripts, frames, exports, temporary files and local Ollama/Whisper model material all belong under `data/`.

Never create new top-level runtime roots such as `logs/`, `database/`, `csv/`, `outputs/`, `downloads/` or model-cache directories. Derive paths from `Settings.data_root` and use `Settings.ensure_local_directories()` to initialize the standard tree.

When sibling modules run on one machine, Data Analysis may consume Collection output directly from this module's configured `data/` path. In distributed mode use configured MongoDB, Redis and S3-compatible storage such as CSC Allas. Manual CSV/JSONL transfer is the fallback.

## Deployment architecture

Execution environment and storage topology are independent configuration dimensions. Do not fork collectors for laptop, server, cron, systemd, agent, local-storage or distributed-storage operation.

Supported dimensions include:

- machine: `laptop`, `linux-server`, `custom`
- execution: `cli`, `cron`, `systemd`, `agent`, `custom`
- browser: `firefox-local`, `worker`, `none`, `custom`
- storage: SQLite/filesystem/memory locally or MongoDB/S3/Redis when distributed

`firefox-local` must bind only to localhost by default. Server schedules must use private `data/runs/` lock/state and `data/logs/` logging. Redis is coordination/settings/queue infrastructure, never the canonical record schema.

## Agent operation

Hermes and other agents must call the same deployment, collector, storage and canonical-record APIs used by the CLI. Do not create a second agent-specific collection stack.

Agent-triggered runs must identify their caller in provenance/execution metadata, normally `hermes-agent`. Agent inspection must redact credentials and private source lists. Dry-run and environment-validation operations must remain offline where practical.

## Architecture

Use `src/laclaugpt_data_collection/`. Keep imports acyclic, platform adapters separate from normalization/storage, and the canonical record envelope stable. Keep local filesystem + SQLite operation working without remote services. Keep browser-extension source under `browser/` with an explicit extraction/transport/storage boundary.

Do not make sibling LaclauGPT repositories mandatory Python dependencies. Interoperate through versioned records, files, or configured services.

## Development

Use Python 3.11+, typed public APIs, `pathlib`, standard logging and lazy optional dependencies. Avoid import-time network/model work and machine-specific paths. Tests must use synthetic fixtures.

Before merging run the public-tree check, Ruff, the configured mypy gate and pytest. Keep GitHub Actions green.

## Legacy migration

Historical repositories are reference implementations, not architecture templates. Classify schema archaeology as `ADOPT`, `ADAPT`, `ALREADY_IMPLEMENTED`, `LEGACY_COMPATIBILITY_ONLY`, `OBSOLETE`, or `PRIVATE_DO_NOT_COPY`, and document non-obvious decisions.
