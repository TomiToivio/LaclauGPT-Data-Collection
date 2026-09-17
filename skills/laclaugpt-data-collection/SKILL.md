# LaclauGPT Data Collection agent skill

Operate Collection through the same canonical APIs used by the CLI. Never create a separate agent-only collector path.

## Scope

Collection owns source/browser/network capture, normalization, canonical source identity, provenance, collection state, raw/media persistence, scheduling and storage adapters. Analysis and Visualization are downstream modules.

## Canonical identity

`source_url` or a stable URI-like identifier is the semantic identity. Platform IDs remain aliases. Mongo `_id`, SQLite keys, filenames and queue IDs never replace `source_url`.

## Deployment modes

Laptop researcher workflow: `machine=laptop`, `execution=cli`, `browser=firefox-local`, local SQLite/filesystem/memory storage. Firefox capture binds to localhost and remains user controlled.

Linux server workflow: `machine=linux-server`, normally `execution=cron` or `systemd`, with `browser=none` unless a worker is explicitly configured. Storage may be local or distributed.

Local storage uses SQLite plus CSV/JSONL/Pandas-compatible files and the repository-local private `data/` filesystem. Distributed storage uses MongoDB for canonical records, Redis for coordination/settings/task queues/messaging, and S3-compatible storage such as CSC Allas for files and large blobs.

CSV/JSONL remains the manual handoff fallback.

## Privacy

All operational source lists, cookies, browser state, credentials, private configs, logs, data, downloads and run state belong below ignored `data/` or external secret/configuration management. Never print or return credentials from an agent tool.

## Hermes operations

Use `laclaugpt_data_collection.integrations.hermes` to inspect redacted configuration, validate environment, plan dry runs, inspect browser readiness and distributed queue capability, and stamp agent-triggered canonical records with caller provenance such as `hermes-agent`.

Dry-run and inspection paths must not contact external websites, Firefox, MongoDB, Redis, S3 or CSC infrastructure.

## Scheduling

Use generated cron/systemd examples rather than writing directly into system configuration. Scheduled execution should use lock/state under `data/runs/` and logs under `data/logs/` to reduce overlapping runs and support restart-safe operation.

## Pipeline handoff

On one machine, Analysis may consume the configured Collection `data/` root directly. In distributed operation, handoff occurs through canonical MongoDB records plus Redis coordination and S3/Allas object references. Do not make sibling repositories mandatory Python imports.

## Cross-module contract conformance

Collection is the first stage of `Collection -> Analysis -> Visualization`, so this module establishes the canonical record every sibling consumes. Three project-wide contracts are normative here and are owned by the meta-repository `TomiToivio/LaclauGPT`:

- `docs/CANONICAL_DATA_CONTRACT.md` — `source_url` is the semantic identity and MUST survive canonicalization and every storage/transport round trip unchanged. Platform identifiers (`document_id`, `video_id`, `new_id`) and backend keys (`_id`, SQLite primary keys, filenames, queue ids) remain aliases and never replace it.
- `docs/STORAGE_BACKEND_CONTRACT.md` — `auto | mongodb | csv` semantics: `auto` uses MongoDB only when an endpoint is explicitly configured and reachable, explicit `mongodb` fails clearly when unavailable, and local CSV/SQLite stays a first-class zero-infrastructure mode.
- `fixtures/cross_module/canonical_parity_v1.json` — the versioned schema-drift tripwire. A repository-local copy is vendored under `tests/fixtures/`; never fork its semantics into a second incompatible fixture.

Run the offline conformance check before proposing a change to the record model, an adapter or the backend selector:

```bash
python tools/verify_contracts.py
```

It verifies fixture construction through the canonical model, that multimodal content is preserved as references only, that review state stays human-controlled, that JSONL/CSV/MongoDB-shape/SQLite reconstruct the same logical record, that the backend selector never invents a remote destination and fails closed on misconfiguration, and that the public-tree policy still passes. It contacts nothing and writes no research data; the exit status is the gate. Note that `Settings` reads a local `.env`, so the endpoint-dependent checks clear the URI explicitly and the tool reports when an ambient `.env` is present.

Do not treat a green unit suite as contract conformance: these checks are deliberately independent of the module's own tests, because a shared-schema break appears as a mismatch *between* modules rather than as a failing unit here.

## Human and agent parity

An agent changes the caller/execution metadata, not the scientific meaning of the record. The same collectors, canonical schemas, storage adapters and privacy checks apply to human CLI, cron/systemd and agent operation.

## Agent roles

A collection agent, a digital ethnographer and a research assistant all operate the canonical API. They differ in what they produce.

- **Data collection agent** — runs the canonical collectors against public sources and submits canonical records. Collects public material broadly, recognises obvious non-relevance, and preserves ambiguous material for later human assessment rather than discarding it at collection time.
- **Digital ethnographer** — searches independently, observes how communities and discourse develop, and writes research notes as a separate, explicitly labelled output.
- **Research assistant** — answers questions about the data, the study configuration and the methodology; summarises collection state; runs bounded queries and scripts. Read-only by default; report before changing state.

A collection agent may file a research note when it makes a substantive observation — an emerging vocabulary, a changed source, a collection bias, a recurring failure. Use the issue tracker for anything that needs human follow-up rather than leaving it in a chat transcript.

Research notes, agent commentary and preliminary observations are interpretations. Store them as a distinct source type, never inside a canonical source record as if they were source content, and never as final findings.

## Working on issues

Never commit to `main` directly. Create a branch first:

```bash
git switch -c issue-<n>-<short-slug>
```

Open a pull request for human review. Push the branch early with a bounded first increment, keep committing to the same branch, and report the branch, the commit and the test status on the issue.

Before proposing a merge, run the repository quality gates: the public-tree check, Ruff, the mypy gate and pytest. All tests must remain offline and synthetic — never make CI depend on MongoDB, Redis, S3/Allas, a browser or private credentials.

If `main` has advanced while you worked, rebase on the updated `main` and re-run the gates. Never force-push a shared branch, and do not merge your own pull request without human review.

## Public-safety checklist before any push

- No credentials, tokens, cookies or browser profiles.
- No private endpoints, hostnames, IP addresses or machine-specific paths.
- No real source/watch lists or private target lists.
- No research data, captures, exports or row-level records.
- Committed study examples use synthetic or public methodology only.
- Generated data and logs remain below the ignored `data/` tree.

Inspect the diff and run the public-tree check before pushing. A passing local test run does not prove the change is publishable.
