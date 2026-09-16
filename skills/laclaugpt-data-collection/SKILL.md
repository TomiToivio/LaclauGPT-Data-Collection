# LaclauGPT Data Collection agent skill

Operate Collection through the same canonical APIs used by the CLI. Never create a separate agent-only collector path.

This skill is written for research agents, coding agents and human contributors. Use an academic, professional and impersonal style by default. Do not assume a particular user identity, political position, institution or personal relationship.

## Research role

A Collection agent may act in three bounded roles:

1. **Data collection agent**: discover, acquire and normalize research-relevant public material through supported collectors.
2. **Digital research assistant**: inspect current collection settings, source coverage, provenance, failures and gaps; propose improvements without silently changing the research design.
3. **Data-collection engineer**: improve collectors, runtime profiles, storage adapters, scheduling and tests while preserving the canonical record contract.

Digital ethnographic observation and preliminary contextual notes may support collection, but final discourse-theoretical interpretation belongs downstream in Data Analysis unless a task explicitly says otherwise.

## Mandatory orientation sequence

Before changing collection logic or proposing new AI26 sources, inspect repository context in this order:

1. `AGENTS.md` — canonical repository contract.
2. `skills/laclaugpt-data-collection/SKILL.md` — this operational skill.
3. `docs/PRIVACY.md` and `docs/RUNTIME_DATA.md` — public/private and runtime boundaries.
4. `configs/studies/<study>.example.yaml` — public study design and collection policy.
5. `configs/studies/<study>.sources.example.toml` — public source manifest and sampling rationale.
6. `configs/studies/<study>.collection-codebook.yaml` — collection-time metadata vocabulary.
7. Relevant deployment documentation such as `docs/DEPLOYMENT_AND_HERMES.md`, `docs/TWO_MACHINE_SETUP.md`, `docs/AI26_LOCALHOST_COLLECTION.md` or `docs/AI26_LASKIN_COLLECTION.md`.
8. Only then inspect legacy repositories for missing implementation patterns or historical settings.

Do not infer that a missing item does not exist until these canonical locations have been checked.

## AI26 canonical lookup map

AI26 is the principal public reference study for the current repository. When a task mentions `AI26`, `Ideological contestation over AI`, `AI elites`, `grassroots`, `parliamentary`, AI ideology sampling, or AI26 collection sources/codebooks, inspect these files first:

```text
configs/studies/ai26.example.yaml
configs/studies/ai26.sources.example.toml
configs/studies/ai26.collection-codebook.yaml
```

Operational copies normally live under ignored runtime paths such as:

```text
data/config/ai26.yaml
data/config/ai26.sources.toml
data/config/ai26.collection-codebook.yaml
```

The checked-in files define the public methodology and default sampling logic. Ignored runtime copies may contain deployment-specific or private extensions. Never replace the public methodology with guesses from an old repository merely because the operational copy is unavailable.

### AI26 source and codebook precedence

Use this precedence when determining what to collect:

1. explicit user/task instructions;
2. current public AI26 study configuration;
3. current public AI26 source manifest;
4. current public AI26 collection codebook;
5. current deployment/runtime overlay, if accessible and safe;
6. current paper/method documentation in the umbrella LaclauGPT repository when needed to resolve research-design ambiguity;
7. legacy repositories only as archaeological evidence for useful sources/settings not yet represented in the current configuration.

Legacy material must be classified before reuse as `ADOPT`, `ADAPT`, `ALREADY_IMPLEMENTED`, `LEGACY_COMPATIBILITY_ONLY`, `OBSOLETE`, or `PRIVATE_DO_NOT_COPY`.

## AI26 conceptual boundaries

AI26 observes ideological contestation around AI/AGI across multiple arenas. Collection-time source selection may use sensitizing categories such as:

- accelerationism / e/acc and adjacent techno-optimism;
- x-risk / catastrophic-risk / doomer discourse;
- AI safety, alignment, evaluation and pacing;
- Critical AI, labour, surveillance, ownership, concentration and environmental/resource critique;
- anti-AI or pause-oriented mobilisation where empirically present;
- mainstream parliamentary, governmental and regulatory discourse;
- frontier-lab, industry and elite discourse;
- grassroots and civil-society discourse.

These categories guide sampling and discovery. They are **not automatic ideological labels for actors or documents**. Collection should preserve evidence and provenance; Data Analysis performs the substantive interpretation.

## Source discovery

Prefer supported, reproducible sources and public interfaces. Depending on the configured study and available collectors, useful source families include:

- RSS/Atom feeds, blogs and newsletters;
- public web pages and policy documents;
- arXiv and other scholarly sources;
- YouTube transcripts, normally transcript-first for AI26;
- browser-assisted capture for X, Instagram, TikTok or other sites when appropriate;
- supported Bluesky, Mastodon, Telegram or API collectors;
- public governmental, parliamentary and regulatory sources.

When proposing a new source, record at least:

- source name and URL/identifier;
- arena and source family;
- sampling rationale;
- geographic/language scope where relevant;
- collection mechanism;
- expected volume/cadence;
- privacy/legal/technical constraints;
- whether it is a public methodology example or private operational target.

Do not grow watch lists without bounds. Prefer interpretable, high-signal samples over indiscriminate scraping.

## Current-events awareness

Collection agents may inspect current public developments to identify new signifiers, actors, controversies and sources. Treat trend detection as source discovery, not as a substitute for the codebook or research design. Proposed changes to AI26 source settings should explain what changed empirically and why the addition improves coverage.

## Canonical identity

`source_url` or a stable URI-like identifier is the semantic identity. Platform IDs remain aliases. Mongo `_id`, SQLite keys, filenames and queue IDs never replace `source_url`.

Preserve raw source payloads and provenance where the collector supports them. Downstream modules should be able to reconstruct where a record came from, when it was collected, and which collector/runtime produced it.

## Deployment modes

Laptop researcher workflow: `machine=laptop`, `execution=cli`, `browser=firefox-local`. Firefox capture binds to localhost and remains user controlled.

Linux server workflow: `machine=linux-server`, normally `execution=cron` or `systemd`, with `browser=none` unless a worker is explicitly configured.

Local storage uses SQLite plus CSV/JSONL/Pandas-compatible files and the repository-local private `data/` filesystem. Distributed storage uses MongoDB for canonical records, Redis for coordination/settings/task queues/messaging, and S3-compatible storage such as CSC Allas for files and large blobs.

CSV/JSONL remains the manual handoff fallback.

## Privacy and research ethics

All operational source lists, cookies, browser state, credentials, private configs, logs, data, downloads and run state belong below ignored `data/` or external secret/configuration management. Never print or return credentials from an agent tool.

Do not copy secrets, private endpoints, cookies, private target lists or row-level research data from historical/private repositories into public files. When legacy code contains mixed useful logic and sensitive values, extract the generalizable pattern and rewrite it against current configuration interfaces.

Preserve platform terms, access controls and applicable research-ethics constraints. Collection code should not bypass authentication or technical controls merely to increase coverage.

## Hermes operation

Hermes is an orchestration/research agent, not a separate data-collection architecture. Use `laclaugpt_data_collection.integrations.hermes` and the same canonical collectors, configuration, storage adapters and records used by CLI/cron operation.

For AI26, Hermes must first load or locate the canonical AI26 study/source/codebook files listed above before planning collection. If an operational copy is unavailable, use the checked-in public templates rather than inventing a new source taxonomy.

Current Hermes model default:

```text
deepseek-v4.1-flash:cloud
```

Model choice does not change the scientific configuration hierarchy. Hermes should retrieve the source manifest/codebook from repository configuration, not attempt to reconstruct them from model memory.

Agent-triggered runs must carry caller/execution provenance such as `hermes-agent`. Configuration inspection must remain redacted. Dry-run and profile validation must not contact external websites or infrastructure.

## Analysis model handoff

Collection does not own final analytical interpretation, but agents working across modules should recognize the current default Ollama analysis model family:

```text
gemma4:12b
gemma4:31b-cloud
gemma4:e2b
```

Do not silently substitute Collection-agent/Hermes models for downstream analytical models. Record model/prompt provenance whenever model-assisted metadata is persisted.

## Scheduling

Use generated cron/systemd examples rather than writing directly into system configuration unless the task explicitly requests installation. Scheduled execution should use lock/state under `data/runs/` or the deployment-specific private runtime directory and logs under `data/logs/` to reduce overlapping runs and support restart-safe operation.

A cron-triggered collector should run one bounded cycle and exit. Do not nest an autonomous scheduler inside cron.

## Pipeline handoff

On one machine, Analysis may consume the configured Collection `data/` root directly. In distributed operation, handoff occurs through canonical MongoDB records plus Redis coordination and S3/Allas object references. Do not make sibling repositories mandatory Python imports.

Collection should preserve:

1. source-side raw metadata/data;
2. normalized canonical content and provenance;
3. file/media references and download state;
4. collection-time research metadata such as arena/source family/sampling rationale;
5. human-readable status or summaries where the current schema defines them.

## Human and agent parity

An agent changes caller/execution metadata, not the scientific meaning of a record. The same collectors, schemas, storage adapters, source manifests, codebooks and privacy checks apply to human CLI, cron/systemd and agent operation.

## Research-quality checks

Before proposing or merging a material change:

- verify that the intended study/source/codebook file actually exists and was consulted;
- check for duplicate sources and overlapping collectors;
- keep collection volume bounded;
- preserve source identity and provenance;
- distinguish public examples from private operational targets;
- add synthetic/offline tests for new logic;
- keep CI independent of private MongoDB/Redis/S3/Ollama credentials;
- document legacy archaeology when it materially shaped the implementation;
- run the repository public-tree check, Ruff, mypy and pytest gates.
