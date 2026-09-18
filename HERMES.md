# HERMES.md

Hermes-style agents must follow `AGENTS.md` as the canonical repository contract and `skills/laclaugpt-data-collection/SKILL.md` for the operational skill.

Before changing runtime paths or data handling, also read `docs/RUNTIME_DATA.md`, `docs/PRIVACY.md`, and `docs/DEPLOYMENT_AND_HERMES.md`.

## Phase 0 / Phase 1 restoration rules

Before any Phase 1 restoration work, inspect `laclaugpt/`.

The hand-coded code in `laclaugpt/` is the Phase 0 foundation. Existing Phase 1 code is reference material. Restore one explicitly requested capability at a time around Phase 0, preserve Phase 0 behavior, prefer wrappers/adapters over rewrites, validate the single step, and stop.

Every `TOMI-LOCKED` marker is a strict invariant unless Tomi explicitly authorizes changing that specific element. This also forbids indirect semantic changes through dependent code, schemas, adapters, tests, configuration, interfaces, or documentation.

Do not interpret broad requests such as “continue Phase 1”, “modernize”, “refactor”, or “clean up” as authorization to redesign the Phase 0 core.

For new Phase 1 infrastructure, the canonical target is:

- MongoDB for canonical records;
- Redis for coordination, cache, state, queues, pub/sub, and lightweight runtime coordination;
- CSC Allas for files, media, large artifacts, exports, and S3-compatible object storage.

Do not add new local-only, SQLite-first, filesystem-only, alternate queue, alternate database, or alternate object-store architectures merely for configurability.

Every runtime or study-specific artifact belongs below the untracked repository-local `data/` root. Do not introduce parallel top-level runtime directories.

Hermes must use the same collectors, data contracts and provenance rules as the human CLI. Do not create an agent-only collection implementation. Agent-triggered runs must carry caller/execution provenance such as `hermes-agent`. Configuration inspection must remain redacted. Dry-run and profile validation must not contact external websites or infrastructure.

Run the offline cross-module contract check (`python tools/verify_contracts.py`) when a change touches the record model, an adapter or backend selection.

## Tasks

You may be asked to act as a developer, research assistant, data analyst or data collection agent. Keep the roles distinguishable. A collection agent, a digital ethnographer and a research assistant share the same canonical API, record contract and privacy boundary, but they produce different things: canonical records, research notes, or answers. Do not quietly turn one into another.

Research notes and agent commentary are interpretations. They are never written into canonical source records as if they were source content, and they never replace human review.

When you make a substantive observation, such as a change in a source, an emerging vocabulary, a collection gap, or a recurring failure, write it down as a note or an issue rather than leaving it only in a chat transcript.

## Branches

Never commit directly to `main`. Create a branch when working on an issue, following the existing convention `issue-<n>-<short-slug>`, and open a pull request for human review.

```bash
git switch -c issue-<n>-<short-slug>
```

Push the branch early with a bounded first increment and keep working on the same branch. Report the branch, the commit and the test status on the issue.

Run the quality gates before proposing a merge: the public-tree check, Ruff, the mypy gate and pytest. If the base branch moved while you worked, rebase and re-run the gates; never force-push.

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
