<!-- PHASE-BRANCH-POLICY:v1 -->

## Mandatory phase-branch policy

LaclauGPT is developed on persistent phase branches: `phase-0`, `phase-1`, `phase-2`, `phase-3`, and `phase-4`.

**Current active/stable phase: Phase 1.** Therefore `main` must represent the current Phase-1 state and must stay synchronized with `phase-1`. The `phase-0` branch remains the preserved Phase 0 baseline and must not be repurposed or advanced.

**Operational rule:** treat `phase-1` as the source branch for current work and `main` as its synchronized public baseline. Do not describe Phase 0 runtime behavior as the current repository default; Phase 0 material is legacy compatibility/rollback context unless a task explicitly targets `phase-0`.

Before making any issue-driven change, an agent MUST determine the issue's intended phase from explicit issue text, title, labels, milestone, linked plan, or repository documentation. Then:

1. Work from the matching persistent phase branch, e.g. a Phase-1 issue starts from `phase-1`, not `main` and not `phase-0`.
2. Prefer a short-lived issue branch created from that phase branch, such as `issue-123-description`, and target the pull request back to the same `phase-N` branch.
3. Never merge later-phase work into `main` while an earlier phase is current. Phase-2 through Phase-4 may advance independently without destabilizing the current Phase 1 line. `phase-0` remains the preserved Phase 0 baseline.
4. Phase-0 maintenance fixes target `phase-0` only and do not move `main` backward. Current development and fixes target `phase-1`; after validation, keep `main` synchronized with `phase-1`.
5. When the project officially advances phases, synchronize `main` to the newly active phase branch only after explicit human approval.
6. If an issue has no phase information, treat it as belonging to the current phase unless the task or surrounding roadmap clearly says otherwise. Currently that means `phase-1`.
7. Do not silently move work between phases. If implementation reveals that an issue belongs to another phase, update/document the issue or report the mismatch before merging.
8. Preserve `TOMI-LOCKED`, privacy, public/private, runtime-data, scientific-method, and module-boundary rules on every phase branch.

See `docs/PHASE_BRANCHING.md` for the repository-wide workflow.

# Agent and Contributor Rules

This repository is public-safe infrastructure. Treat every commit as publishable.

This file is the canonical shared contract. Agent-specific files such as `CLAUDE.md`, `HERMES.md`, and `CODEX.md` may add workflow guidance but must not override this file, `docs/PRIVACY.md`, `docs/RUNTIME_DATA.md`, or CI.

## Scope

Keep this repository limited to data collection: source/browser/network capture, platform parsers, normalization, provenance, collection state, media/raw persistence, scheduling, and storage adapters. Analysis, dashboards, simulations and other module responsibilities belong elsewhere.

## Phase 0 foundation and Phase 1 restoration

The hand-coded implementation under `laclaugpt/` is the Phase 0 foundation for this module.

Agents MUST inspect `laclaugpt/` first before proposing or implementing Phase 1 work. Existing Phase 1 code outside `laclaugpt/` is a reference implementation and source of isolated functionality, tests, schemas, and interfaces. It is not automatically the canonical architecture.

Phase 1 must be rebuilt incrementally around the working Phase 0 core:

1. Start from the current behavior in `laclaugpt/`.
2. Restore exactly one explicitly requested Phase 1 capability.
3. Make the smallest practical change around Phase 0, preferring adapters or wrappers over rewrites.
4. Preserve existing Phase 0 behavior unless the task explicitly says otherwise.
5. Validate that one restoration step.
6. Stop.

Do not perform big-bang restorations, speculative redesigns, architecture cleanups, broad refactors, or migrations unless explicitly requested. Broad requests such as “continue Phase 1”, “modernize”, “refactor”, or “clean up” do not authorize rewriting the Phase 0 core.

When Phase 0 and old Phase 1 code differ, preserve Phase 0 and surface the difference unless the task explicitly instructs otherwise.

## TOMI-LOCKED invariants

Any element marked `TOMI-LOCKED` is immutable unless Tomi explicitly authorizes changing that specific element.

This includes direct and indirect changes. Do not change dependent code, schemas, adapters, tests, configuration, interfaces, or documentation in a way that changes the semantics of a locked element.

Before editing `laclaugpt/` or anything that depends on it, search for `TOMI-LOCKED` markers and treat them as strict invariants.

## AI26 public reference study

AI26 (`Ideological contestation over AI`) is the preferred realistic public example for this module because the current LaclauGPT architecture is being developed alongside the public AI26 paper. Use `configs/studies/ai26.example.yaml` when documenting or testing study-aware collection behavior.

AI26 example configuration is allowed to contain public methodology: the three paper arenas (AI elites, grassroots mobilisation, parliamentary/electoral politics), public source-family examples, discovery terms, project metadata and secret-free collection/storage policies. These settings are sampling provenance only. Collection MUST NOT infer or assign ideological formations, discourse roles or actor ideology from the source list.

The public example may track changing research-relevant terms such as safety, pacing, competition, innovation, China, control, liability, independent evaluation, regulation, labour, ownership, surveillance and data centres. These are discovery/context hints, not labels.

Keep private credentials, cookies, browser profiles, private backend endpoints, unpublished watch lists/handles, private source-selection notes and row-level research data. The public/private rule is **public research design and examples, private operational state and data**.

## Canonical record contract

All collectors and storage adapters MUST use the project-wide canonical LaclauGPT record contract.

- `source_url` or a stable URI-like equivalent is the semantic source identity.
- Canonicalize source identity deterministically before persistence.
- Platform-native IDs belong in `source_native_ids`; they never replace `source_url`.
- Mongo `_id`, CSV row numbers and local filenames are backend details, not research identities.
- Collection populates `source`, source-side `content`, media/file references and collection provenance. Analysis enriches the same record later.
- Text-only records are valid. Do not invent multimodal fields.
- Flat legacy fields are accepted only through bounded adapters. Persisted canonical records use structured sections.
- Every persisted schema change requires an explicit schema-version decision, migration note and synthetic round-trip contract tests.

`NormalizedRecord` is a compatibility constructor for existing collectors, not a second persistent schema.

## Runtime data boundary

All runtime and operational study material belongs below `data/`, and the complete `data/` tree stays outside Git. Follow `docs/RUNTIME_DATA.md`.

Logs, local configuration, private codebooks, private source/target lists, downloads, media, browser state, transcripts, frames, exports, temporary files and local model material all belong under `data/`. Public-safe study examples such as `configs/studies/ai26.example.yaml` live outside `data/`.

Never create new top-level runtime roots such as `logs/`, `database/`, `csv/`, `outputs/`, `downloads/` or model-cache directories.

## Canonical deployment architecture

The canonical architecture targets distributed operation:

- **MongoDB** for canonical records and document persistence.
- **Redis** for coordination, cache, state, queues, pub/sub, and lightweight runtime coordination.
- **CSC Allas** for files, media, large artifacts, exports, and S3-compatible object storage.
- CSC Allas authentication uses `allas-conf`.

Do not add new local-only, SQLite-first, filesystem-only, alternate object-store, alternate queue, or alternate database architectures merely for configurability. Existing legacy modes may remain only where needed for compatibility, but new Phase 1 work must target MongoDB + Redis + CSC Allas unless Tomi explicitly requests otherwise.

Redis is coordination infrastructure, never the canonical record schema.

## Agent operation

Hermes and other agents must use the same collection behavior and data contracts used by the human CLI. Do not create a second agent-specific collection stack.

Agent-triggered runs must identify their caller in provenance/execution metadata, normally `hermes-agent`. Agent inspection must redact credentials and private source lists. Dry-run and environment-validation operations must remain offline where practical.

## Agent roles

Agent-assisted work in this repository falls into three roles. The same canonical API, record contract and privacy boundary apply to all of them; only the output differs.

- **Data collection agent.** Runs the canonical collectors against public sources and submits canonical records. Recognises relevance, filters obvious non-relevance, preserves ambiguous material for later human assessment, records source identity and collection provenance, and leaves interpretation to Analysis.
- **Digital ethnographer.** Independently searches for relevant public material, observes how communities and discourse change over time, and writes separate research notes. Notes are researcher interpretation, not participant speech, and must be stored as a distinct source type rather than merged into collected records.
- **Research assistant.** Answers questions about the project, the collected data and the methodology; inspects and summarises collection state; runs bounded read-only queries and scripts; and reports trends, gaps or blockers.

A collection agent may also file a research note when it makes a substantive observation. Keep the roles distinguishable: do not let one role silently perform another's interpretation.

Research notes and agent commentary are interpretations and must not be written into canonical source records as if they were source content.

## Architecture

Treat `laclaugpt/` as the canonical Phase 0 behavioral foundation. Phase 1 code in `src/laclaugpt_data_collection/` may be reused, adapted, wrapped, or restored around Phase 0 one capability at a time, but must not silently replace it.

Keep browser-extension source under `browser/` with an explicit extraction/transport/storage boundary. Do not make sibling LaclauGPT repositories mandatory Python dependencies. Interoperate through versioned records, files, or configured services.

## Branches and pull requests

Never commit directly to `main`.

When working on a tracked issue, create a branch first and open a pull request for review. Follow the existing naming convention:

```bash
git switch -c issue-<n>-<short-slug>
```

`feature/issue-<n>-<short-slug>` is also accepted. Keep the branch focused on that issue; do not bundle unrelated refactors or formatting sweeps.

Push the branch and open the pull request early with a bounded first increment, then keep committing to the same branch. Report the branch name, the commit and the test status in the issue. A pull request is ready to merge only when the public-tree check, Ruff, the mypy gate and pytest are green and no private material has been introduced.

Do not merge your own pull request without human review. If the base branch has advanced while you worked, rebase on the updated base and re-run the quality gates rather than force-pushing. Never force-push a shared branch.

## Development

Use Python 3.11+, typed public APIs, `pathlib`, standard logging and lazy optional dependencies. Avoid import-time network/model work and machine-specific paths. Tests must use synthetic fixtures.

Before merging run the public-tree check, Ruff, the configured mypy gate and pytest. Keep GitHub Actions green.

## Legacy migration

Historical repositories are reference implementations, not architecture templates. Classify schema archaeology as `ADOPT`, `ADAPT`, `ALREADY_IMPLEMENTED`, `LEGACY_COMPATIBILITY_ONLY`, `OBSOLETE`, or `PRIVATE_DO_NOT_COPY`, and document non-obvious decisions.

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

