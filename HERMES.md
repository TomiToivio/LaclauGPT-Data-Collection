# HERMES.md

Hermes-style agents must follow `AGENTS.md` as the canonical repository contract and `skills/laclaugpt-data-collection/SKILL.md` for the operational skill.

Before changing runtime paths or data handling, also read `docs/RUNTIME_DATA.md`, `docs/PRIVACY.md`, and `docs/DEPLOYMENT_AND_HERMES.md`.

Every runtime or study-specific artifact belongs below the untracked repository-local `data/` root. Do not introduce parallel top-level runtime directories. Use the canonical path helpers and initializer in `src/laclaugpt_data_collection/config.py`.

Hermes must use `laclaugpt_data_collection.integrations.hermes` and the same canonical collectors, configuration, storage adapters and record contract as the human CLI. Do not create an agent-only collection implementation.

Agent-triggered runs must carry caller/execution provenance such as `hermes-agent`. Configuration inspection must remain redacted. Dry-run and profile validation must not contact external websites or infrastructure.

For local sibling-module operation, downstream Analysis may read this module's configured `data/` tree directly. Distributed operation uses MongoDB for canonical records, Redis for coordination/task queues/messaging, and S3-compatible storage such as CSC Allas for files. CSV/JSONL remains the manual fallback.

Run the offline cross-module contract check (`python tools/verify_contracts.py`) when a change touches the record model, an adapter or the backend selector.

Keep collection responsibilities narrow, preserve `source_url` identity across deployment/storage profiles, add synthetic tests, and run the repository quality gates before proposing a merge.

## Tasks

You may be asked to act as a developer, research assistant, data analyst or data collection agent. Do these tasks with a professional attitude.

Keep the roles distinguishable. A collection agent, a digital ethnographer and a research assistant share the same canonical API, record contract and privacy boundary, but they produce different things: canonical records, research notes, or answers. Do not quietly turn one into another.

Research notes and agent commentary are interpretations. They are never written into canonical source records as if they were source content, and they never replace human review.

When you make a substantive observation — a change in a source, an emerging vocabulary, a collection gap, a recurring failure — write it down as a note or an issue rather than leaving it in a chat transcript.

## Branches

Never commit directly to `main`. Create a branch when working on an issue, following the existing convention `issue-<n>-<short-slug>`, and open a pull request for human review.

```bash
git switch -c issue-<n>-<short-slug>
```

Push the branch early with a bounded first increment and keep working on the same branch. Report the branch, the commit and the test status on the issue.

Run the quality gates before proposing a merge: the public-tree check, Ruff, the mypy gate and pytest. If `main` moved while you worked, rebase and re-run the gates; never force-push.