# HERMES.md

Hermes-style agents must follow `AGENTS.md` as the canonical repository contract.

Before changing runtime paths or data handling, also read `docs/RUNTIME_DATA.md` and `docs/PRIVACY.md`.

Every runtime or study-specific artifact belongs below the untracked repository-local `data/` root. Do not introduce parallel top-level runtime directories. Use the canonical path helpers and initializer in `src/laclaugpt_data_collection/config.py`.

For local sibling-module operation, downstream Analysis may read this module's configured `data/` tree directly. Distributed and CSV/JSONL fallback rules are defined in `docs/RUNTIME_DATA.md`.

Keep collection responsibilities narrow, preserve stable normalized records, add synthetic tests, and run the repository quality gates before proposing a merge.
