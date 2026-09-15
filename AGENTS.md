# Agent and Contributor Rules

This repository is public-safe infrastructure. Treat every commit as publishable.

This file is the canonical shared contract. Agent-specific files such as `CLAUDE.md`, `HERMES.md`, and `CODEX.md` may add workflow guidance but must not override this file, `docs/PRIVACY.md`, `docs/RUNTIME_DATA.md`, or CI.

## Scope

Keep this repository limited to data collection: source/browser/network capture, platform parsers, normalization, provenance, collection state, media/raw persistence, scheduling, and storage adapters. Analysis, dashboards, simulations and other module responsibilities belong elsewhere.

## Mandatory runtime data boundary

All runtime and study-specific material belongs below `data/`, and the complete `data/` tree stays outside Git. Follow `docs/RUNTIME_DATA.md`.

Logs, databases, local configuration, CSV/JSONL files, codebooks, source/target lists, downloads, media, browser state, transcripts, frames, exports, temporary files and local Ollama/Whisper model material all belong under `data/`.

Never create new top-level runtime roots such as `logs/`, `database/`, `csv/`, `outputs/`, `downloads/` or model-cache directories. Derive paths from `Settings.data_root` and use `Settings.ensure_local_directories()` to initialize the standard tree.

When sibling modules run on one machine, Data Analysis may consume Collection output directly from this module's configured `data/` path. In distributed mode use configured MongoDB, Redis and S3-compatible storage such as CSC Allas. Manual CSV/JSONL transfer is the fallback.

## Architecture

Use `src/laclaugpt_data_collection/`. Keep imports acyclic, platform adapters separate from normalization/storage, and the normalized record envelope stable. Keep local filesystem + SQLite operation working without remote services. Keep browser-extension source under `browser/` with an explicit extraction/transport/storage boundary.

Do not make sibling LaclauGPT repositories mandatory Python dependencies. Interoperate through versioned records, files, or configured services.

## Development

Use Python 3.11+, typed public APIs, `pathlib`, standard logging and lazy optional dependencies. Avoid import-time network/model work and machine-specific paths. Tests must use synthetic fixtures.

Before merging run the public-tree check, Ruff, the configured mypy gate and pytest. Keep GitHub Actions green.

## Legacy migration

Historical repositories are reference implementations, not architecture templates. Classify substantial migrations as `MIGRATE`, `ALREADY_IMPLEMENTED`, `REIMPLEMENT_CLEANLY`, `OBSOLETE`, or `PRIVATE_OR_OPERATIONAL_DO_NOT_COPY` and document non-obvious decisions.
