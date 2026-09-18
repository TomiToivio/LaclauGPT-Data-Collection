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

Keep changes inside the existing `src/` architecture, preserve stable normalized records and provenance, add synthetic tests, and run the repository quality gates before merging.

## TOMI-LOCKED

Anything marked `TOMI-LOCKED` is a human-controlled invariant.

Agents MUST NOT modify, refactor, rename, migrate, remove, reinterpret, or change the semantics of a TOMI-LOCKED element.

This includes indirect changes whose effect would alter a locked interface, data format, workflow, behavior, assumption, prompt, schema, configuration, or documented contract.

When an agent encounters `TOMI-LOCKED`:

1. Preserve the marked element exactly unless Tomi's current instruction explicitly authorizes changing that specific locked element.
2. Do not bypass the lock through dependent code, schemas, serializers, migrations, tests, prompts, documentation, interfaces, configuration, or compatibility layers.
3. Do not remove the `TOMI-LOCKED` marker during cleanup, refactoring, migration, modernization, or documentation work.
4. Broad instructions such as "refactor", "modernize", "fix everything", "make CI green", "update the pipeline", or similar do NOT override a lock.
5. If a requested task conflicts with a locked element, preserve the lock, complete any non-conflicting work that is safe to do, and clearly report the conflict.
6. If Tomi explicitly authorizes a change to a specific locked element, that element may be changed, but the `TOMI-LOCKED` marker remains unless Tomi explicitly asks to remove the lock itself.

Only explicit authorization from Tomi for the specific locked element overrides the lock.

Marker examples:

```python
# TOMI-LOCKED
# Do not modify without explicit approval from Tomi.
```

```markdown
<!-- TOMI-LOCKED -->
```

```yaml
# TOMI-LOCKED
```

The marker is intentionally grep-friendly:

```bash
grep -R "TOMI-LOCKED" .
```

