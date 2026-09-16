# Agent and Contributor Rules

This repository is public-safe infrastructure. Treat every commit as publishable.

This file is the canonical shared contract. Agent-specific files such as `CLAUDE.md`, `HERMES.md`, and `CODEX.md` may add workflow guidance but must not override this file, `docs/PRIVACY.md`, `docs/RUNTIME_DATA.md`, or CI.

## Scope

Keep this repository limited to data collection: source/browser/network capture, platform parsers, normalization, provenance, collection state, media/raw persistence, scheduling, and storage adapters. Analysis, dashboards, simulations and other module responsibilities belong elsewhere.

## AI26 public reference study

AI26 (`Ideological contestation over AI`) is the preferred realistic public example for this module because the current LaclauGPT architecture is being developed alongside the public AI26 paper. Use `configs/studies/ai26.example.yaml` when documenting or testing study-aware collection behavior.

AI26 example configuration is allowed to contain public methodology: the three paper arenas (AI elites, grassroots mobilisation, parliamentary/electoral politics), public source-family examples, discovery terms, project metadata and secret-free collection/storage policies. These settings are sampling provenance only. Collection MUST NOT infer or assign ideological formations, discourse roles or actor ideology from the source list.

The public example may track changing research-relevant terms such as safety, pacing, competition, innovation, China, control, liability, independent evaluation, regulation, labour, ownership, surveillance and data centres. These are discovery/context hints, not labels.

Keep private credentials, cookies, browser profiles, private backend endpoints, unpublished watch lists/handles, private source-selection notes and row-level research data. The public/private rule is **public research design and examples, private operational state and data**.

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

All runtime and operational study material belongs below `data/`, and the complete `data/` tree stays outside Git. Follow `docs/RUNTIME_DATA.md`.

Logs, databases, local configuration, CSV/JSONL files, private codebooks, private source/target lists, downloads, media, browser state, transcripts, frames, exports, temporary files and local Ollama/Whisper model material all belong under `data/`. Public-safe study examples such as `configs/studies/ai26.example.yaml` live outside `data/`.

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

## Agent roles

Agent-assisted work in this repository falls into three roles. The same canonical API, record contract and privacy boundary apply to all of them; only the output differs.

- **Data collection agent.** Runs the canonical collectors against public sources and submits canonical records. Recognises relevance, filters obvious non-relevance, preserves ambiguous material for later human assessment, records source identity and collection provenance, and leaves interpretation to Analysis.
- **Digital ethnographer.** Independently searches for relevant public material, observes how communities and discourse change over time, and writes separate research notes. Notes are researcher interpretation, not participant speech, and must be stored as a distinct source type rather than merged into collected records.
- **Research assistant.** Answers questions about the project, the collected data and the methodology; inspects and summarises collection state; runs bounded read-only queries and scripts; and reports trends, gaps or blockers.

A collection agent may also file a research note when it makes a substantive observation. Keep the roles distinguishable: do not let one role silently perform another's interpretation.

Research notes and agent commentary are interpretations and must not be written into canonical source records as if they were source content.

## Architecture

Use `src/laclaugpt_data_collection/`. Keep imports acyclic, platform adapters separate from normalization/storage, and the canonical record envelope stable. Keep local filesystem + SQLite operation working without remote services. Keep browser-extension source under `browser/` with an explicit extraction/transport/storage boundary.

Do not make sibling LaclauGPT repositories mandatory Python dependencies. Interoperate through versioned records, files, or configured services.

## Branches and pull requests

Never commit directly to `main`.

When working on a tracked issue, create a branch first and open a pull request for review. Follow the existing naming convention:

```bash
git switch -c issue-<n>-<short-slug>
```

`feature/issue-<n>-<short-slug>` is also accepted. Keep the branch focused on that issue; do not bundle unrelated refactors or formatting sweeps.

Push the branch and open the pull request early with a bounded first increment, then keep committing to the same branch. Report the branch name, the commit and the test status in the issue. A pull request is ready to merge only when the public-tree check, Ruff, the mypy gate and pytest are green and no private material has been introduced.

Do not merge your own pull request without human review. If `main` has advanced while you worked, rebase on the updated `main` and re-run the quality gates rather than force-pushing. Never force-push a shared branch.

## Development

Use Python 3.11+, typed public APIs, `pathlib`, standard logging and lazy optional dependencies. Avoid import-time network/model work and machine-specific paths. Tests must use synthetic fixtures.

Before merging run the public-tree check, Ruff, the configured mypy gate and pytest. Keep GitHub Actions green.

## Legacy migration

Historical repositories are reference implementations, not architecture templates. Classify schema archaeology as `ADOPT`, `ADAPT`, `ALREADY_IMPLEMENTED`, `LEGACY_COMPATIBILITY_ONLY`, `OBSOLETE`, or `PRIVATE_DO_NOT_COPY`, and document non-obvious decisions.
