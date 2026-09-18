# CODEX.md

Codex and other coding agents must follow `AGENTS.md` as the canonical repository contract.

Before changing runtime paths or data handling, also read `docs/RUNTIME_DATA.md` and `docs/PRIVACY.md`.

For Phase 0 / Phase 1 work:

- inspect `laclaugpt/` before editing;
- preserve the hand-coded Phase 0 implementation and its behavior;
- never modify a `TOMI-LOCKED` element or its semantics without explicit authorization;
- restore exactly one requested Phase 1 capability per task;
- prefer small adapters/wrappers over replacing Phase 0 logic;
- use old Phase 1 code under `src/` as a reference implementation, not as an automatic source of architectural authority;
- target MongoDB + Redis + CSC Allas for canonical distributed infrastructure;
- do not invent new SQLite-first, filesystem-only, alternate queue, alternate database, or alternate object-store modes for configurability;
- avoid unrelated refactors and stop after the bounded task is complete.

Every runtime or study-specific artifact belongs below the untracked repository-local `data/` root.

Preserve stable normalized records and provenance, add synthetic tests where appropriate, and run the repository quality gates before proposing a merge.
