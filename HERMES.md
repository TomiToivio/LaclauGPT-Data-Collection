# HERMES.md

Hermes-style agents must follow `AGENTS.md` as the canonical repository contract and `skills/laclaugpt-data-collection/SKILL.md` for the operational skill.

Before changing runtime paths or data handling, also read `docs/RUNTIME_DATA.md`, `docs/PRIVACY.md`, and `docs/DEPLOYMENT_AND_HERMES.md`.

Every runtime or study-specific artifact belongs below the untracked repository-local `data/` root. Do not introduce parallel top-level runtime directories. Use the canonical path helpers and initializer in `src/laclaugpt_data_collection/config.py`.

Hermes must use `laclaugpt_data_collection.integrations.hermes` and the same canonical collectors, configuration, storage adapters and record contract as the human CLI. Do not create an agent-only collection implementation.

Agent-triggered runs must carry caller/execution provenance such as `hermes-agent`. Configuration inspection must remain redacted. Dry-run and profile validation must not contact external websites or infrastructure.

For local sibling-module operation, downstream Analysis may read this module's configured `data/` tree directly. Distributed operation uses MongoDB for canonical records, Redis for coordination/task queues/messaging, and S3-compatible storage such as CSC Allas for files. CSV/JSONL remains the manual fallback.

Keep collection responsibilities narrow, preserve `source_url` identity across deployment/storage profiles, add synthetic tests, and run the repository quality gates before proposing a merge.

## Tasks

You may be asked to act as a developer, research assistant, data analyst or data collection agent. Do these tasks with a professional attitude.

## Branches

Create a branch when working on an issue.