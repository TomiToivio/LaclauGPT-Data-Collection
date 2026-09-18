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
