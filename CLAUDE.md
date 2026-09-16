# CLAUDE.md

Claude Code must follow `AGENTS.md` as the canonical repository contract and `skills/laclaugpt-data-collection/SKILL.md` for collection-specific workflow.

Before changing runtime paths or data handling, also read `docs/RUNTIME_DATA.md` and `docs/PRIVACY.md`.

For AI26 work, inspect these files before searching legacy repositories or inventing settings:

```text
configs/studies/ai26.example.yaml
configs/studies/ai26.sources.example.toml
configs/studies/ai26.collection-codebook.yaml
```

They are the canonical public study design, source manifest and collection-time codebook. Private runtime copies may exist under ignored `data/config/`; if unavailable, use the checked-in templates rather than guessing.

Key rule: every runtime or study-specific artifact is stored below the untracked repository-local `data/` root. Do not create alternative top-level runtime directories. Use the path helpers and initialization behavior defined in `src/laclaugpt_data_collection/config.py`.

For local sibling-module operation, downstream Analysis may read this module's configured `data/` tree directly. Distributed and manual interchange rules are defined in `docs/RUNTIME_DATA.md`.

Use an academic, neutral style in research-facing documentation. Keep source discovery separate from final ideological interpretation.

Run the repository's public-tree check, lint/type checks, and tests before merging.
