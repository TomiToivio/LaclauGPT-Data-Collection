# CLAUDE.md

Claude Code must follow `AGENTS.md` as the canonical repository contract.

Before changing runtime paths or data handling, also read `docs/RUNTIME_DATA.md` and `docs/PRIVACY.md`.

For Phase 0 / Phase 1 work:

- inspect `laclaugpt/` first;
- preserve Phase 0 behavior;
- treat every `TOMI-LOCKED` marker as immutable unless Tomi explicitly authorizes that exact change;
- restore only one explicitly requested Phase 1 capability at a time;
- prefer wrappers/adapters around Phase 0 over rewrites;
- treat existing `src/` code as a reference/source of functionality, not automatically as the canonical architecture;
- target MongoDB + Redis + CSC Allas for new Phase 1 infrastructure;
- do not add alternate local-only storage/deployment architectures unless explicitly requested;
- stop when the requested restoration step is complete.

Every runtime or study-specific artifact belongs below the untracked repository-local `data/` root. Do not create alternative top-level runtime directories.

Run the repository's public-tree check, lint/type checks, and tests before proposing a merge.
