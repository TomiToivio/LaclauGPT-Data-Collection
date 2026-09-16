# HERMES.md

Hermes-style agents must follow `AGENTS.md` as the canonical repository contract and `skills/laclaugpt-data-collection/SKILL.md` for the operational skill.

Use an academic, professional and neutral working style. Do not assume a particular researcher's identity, political commitments, personal preferences or informal persona.

Before changing runtime paths or data handling, also read `docs/RUNTIME_DATA.md`, `docs/PRIVACY.md`, and `docs/DEPLOYMENT_AND_HERMES.md`.

## AI26: do not guess where the settings are

When the task concerns AI26, first inspect these files in this repository:

```text
configs/studies/ai26.example.yaml
configs/studies/ai26.sources.example.toml
configs/studies/ai26.collection-codebook.yaml
```

Treat them as the canonical public starting point for:

- AI26 arenas and collection policy;
- source families and public-safe example sources;
- source budgets and sampling rationale;
- collection-time metadata/codebook fields;
- discovery hints and sensitizing categories.

Operational copies may exist below ignored `data/config/`. If they are unavailable, use the checked-in public templates. Do **not** reconstruct the AI26 source list or codebook from LLM memory.

Only inspect old LaclauGPT/CyborgAnthropology repositories after checking the current files above, and then only to recover missing public-safe source ideas, old codebook concepts or implementation patterns. Never copy credentials, cookies, private endpoints, private watch lists or row-level research material.

## Hermes model

The current Hermes default is:

```text
deepseek-v4.1-flash:cloud
```

Hermes is not intentionally a reduced-capability or "dumb" model. The important constraint is architectural: the model must retrieve study configuration from the repository instead of inventing it.

Downstream analytical work normally uses the configured analysis models, currently one of:

```text
gemma4:12b
gemma4:31b-cloud
gemma4:e2b
```

Do not silently substitute the Hermes orchestration model for the analysis model family.

## Operation

Every runtime or study-specific artifact belongs below the untracked repository-local `data/` root. Do not introduce parallel top-level runtime directories. Use the canonical path helpers and initializer in `src/laclaugpt_data_collection/config.py`.

Hermes must use `laclaugpt_data_collection.integrations.hermes` and the same canonical collectors, configuration, storage adapters and record contract as the human CLI. Do not create an agent-only collection implementation.

Hermes may:

- inspect redacted effective configuration;
- inspect AI26 public study/source/codebook files;
- compare current coverage against public developments;
- propose source additions/removals with sampling rationale;
- validate deployment profiles;
- plan bounded collection runs;
- invoke canonical collectors when explicitly permitted by the task/runtime.

Hermes must not:

- invent a parallel AI26 taxonomy when canonical files exist;
- assign final ideology labels during collection;
- silently mutate private target lists or distributed settings;
- treat source-family hints as actor ideology;
- create an agent-only crawler or storage schema.

Agent-triggered runs must carry caller/execution provenance such as `hermes-agent`. Configuration inspection must remain redacted. Dry-run and profile validation must not contact external websites or infrastructure.

For local sibling-module operation, downstream Analysis may read this module's configured `data/` tree directly. Distributed operation uses MongoDB for canonical records, Redis for coordination/task queues/messaging, and S3-compatible storage such as CSC Allas for files. CSV/JSONL remains the manual fallback.

Keep collection responsibilities narrow, preserve `source_url` identity across deployment/storage profiles, add synthetic tests, and run the repository quality gates before proposing a merge.
