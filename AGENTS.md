# Agent and Contributor Rules

This repository is public-safe infrastructure. Treat every commit as publishable.

This file is the canonical shared contract. Agent-specific files such as `CLAUDE.md`, `HERMES.md`, and `CODEX.md` may add workflow guidance but must not override this file, `docs/PRIVACY.md`, `docs/RUNTIME_DATA.md`, or CI.

Agents should communicate in an academic, professional and impersonal style by default. Do not assume a particular user's identity, institution, ideology, preferences or personal relationship unless a task explicitly requires that context.

## Scope

Keep this repository limited to data collection: source/browser/network capture, platform parsers, normalization, provenance, collection state, media/raw persistence, scheduling, and storage adapters. Analysis, dashboards, simulations and other module responsibilities belong elsewhere.

## Mandatory agent orientation

Before editing collection settings or proposing new sources, read:

1. `AGENTS.md`;
2. `skills/laclaugpt-data-collection/SKILL.md`;
3. `docs/PRIVACY.md` and `docs/RUNTIME_DATA.md`;
4. the relevant `configs/studies/<study>.*` files;
5. deployment documentation relevant to the target machine/workflow.

Do not search legacy repositories first when current canonical configuration already exists.

## AI26 public reference study

AI26 (`Ideological contestation over AI`) is the preferred realistic public example for this module because the current LaclauGPT architecture is being developed alongside the public AI26 paper.

For AI26, agents MUST inspect these current files before improvising settings or searching historical repositories:

```text
configs/studies/ai26.example.yaml
configs/studies/ai26.sources.example.toml
configs/studies/ai26.collection-codebook.yaml
```

These three files answer different questions:

- `ai26.example.yaml`: research design, arenas, platforms, budgets and collection policy;
- `ai26.sources.example.toml`: concrete public-safe source examples and sampling rationales;
- `ai26.collection-codebook.yaml`: collection-time metadata/codebook vocabulary.

Operational/private copies belong under ignored `data/config/` and may extend the public templates. If those private copies are unavailable, use the public templates rather than reconstructing AI26 from model memory.

AI26 example configuration is allowed to contain public methodology: the three paper arenas (AI elites, grassroots mobilisation, parliamentary/electoral politics), public source-family examples, discovery terms, project metadata and secret-free collection/storage policies. These settings are sampling provenance only. Collection MUST NOT infer or assign ideological formations, discourse roles or actor ideology from the source list.

The public example may track changing research-relevant terms such as safety, pacing, competition, innovation, China, control, liability, independent evaluation, regulation, labour, ownership, surveillance and data centres. These are discovery/context hints, not labels.

Keep private credentials, cookies, browser profiles, private backend endpoints, unpublished watch lists/handles, private source-selection notes and row-level research data private. The public/private rule is **public research design and examples, private operational state and data**.

## Research-agent roles

Agents may support three bounded roles inside Collection:

- **data collection**: acquire and normalize material using supported collectors;
- **research assistance**: inspect source coverage, current developments and collection gaps, and propose changes with rationale;
- **collection engineering**: improve collectors, deployment, storage and tests.

Digital ethnographic notes or preliminary contextual summaries may support source discovery, but final discourse interpretation belongs to Data Analysis unless explicitly requested otherwise.

When suggesting a source, record the source identifier/URL, arena, source family, sampling rationale, geographic/language scope where relevant, expected cadence/volume, collection mechanism and public/private status.

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

Hermes' current default model is `deepseek-v4.1-flash:cloud`. Model memory is never authoritative for study settings: Hermes must retrieve AI26 sources and codebooks from repository configuration.

Current downstream analysis-model defaults are `gemma4:12b`, `gemma4:31b-cloud`, or `gemma4:e2b`. Collection must not silently replace those with the Hermes orchestration model.

## Architecture

Use `src/laclaugpt_data_collection/`. Keep imports acyclic, platform adapters separate from normalization/storage, and the canonical record envelope stable. Keep local filesystem + SQLite operation working without remote services. Keep browser-extension source under `browser/` with an explicit extraction/transport/storage boundary.

Do not make sibling LaclauGPT repositories mandatory Python dependencies. Interoperate through versioned records, files, or configured services.

## Development

Use Python 3.11+, typed public APIs, `pathlib`, standard logging and lazy optional dependencies. Avoid import-time network/model work and machine-specific paths. Tests must use synthetic fixtures.

Before merging run the public-tree check, Ruff, the configured mypy gate and pytest. Keep GitHub Actions green.

## Legacy migration

Historical repositories are reference implementations, not architecture templates. Classify schema/settings archaeology as `ADOPT`, `ADAPT`, `ALREADY_IMPLEMENTED`, `LEGACY_COMPATIBILITY_ONLY`, `OBSOLETE`, or `PRIVATE_DO_NOT_COPY`, and document non-obvious decisions.

When legacy files contain useful AI26 sources, codebooks or prompts mixed with obsolete architecture or private values, extract only the generalizable research configuration and rewrite it against the current canonical files. Never copy private runtime values into public configuration.
