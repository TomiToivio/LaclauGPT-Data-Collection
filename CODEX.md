# CODEX.md

Codex and other coding agents must follow `AGENTS.md` as the canonical repository contract and `skills/laclaugpt-data-collection/SKILL.md` for collection-specific workflow.

Before changing runtime paths or data handling, also read `docs/RUNTIME_DATA.md` and `docs/PRIVACY.md`.

For AI26 work, inspect these files before searching historical repositories or inferring settings from memory:

```text
configs/studies/ai26.example.yaml
configs/studies/ai26.sources.example.toml
configs/studies/ai26.collection-codebook.yaml
```

Use them as the canonical public study design, source manifest and collection-time codebook. Operational/private copies may exist under ignored `data/config/`.

Every runtime or study-specific artifact belongs below the untracked repository-local `data/` root. Do not introduce parallel top-level runtime directories. Use the canonical path helpers and initializer in `src/laclaugpt_data_collection/config.py`.

For local sibling-module operation, downstream Analysis may read this module's configured `data/` tree directly. Distributed and CSV/JSONL fallback rules are defined in `docs/RUNTIME_DATA.md`.

Keep changes inside the existing `src/` architecture, preserve stable normalized records and provenance, add synthetic tests, and run the repository quality gates before merging.
