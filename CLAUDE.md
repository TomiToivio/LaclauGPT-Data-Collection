# CLAUDE.md

Claude Code must follow `AGENTS.md` as the canonical repository contract.

Before changing runtime paths or data handling, also read `docs/RUNTIME_DATA.md` and `docs/PRIVACY.md`.

Key rule: every runtime or study-specific artifact is stored below the untracked repository-local `data/` root. Do not create alternative top-level runtime directories. Use the path helpers and initialization behavior defined in `src/laclaugpt_data_collection/config.py`.

For local sibling-module operation, downstream Analysis may read this module's configured `data/` tree directly. Distributed and manual interchange rules are defined in `docs/RUNTIME_DATA.md`.

Run the repository's public-tree check, lint/type checks, and tests before merging.
