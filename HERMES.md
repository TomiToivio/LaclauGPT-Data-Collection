# HERMES.md

Guidance for Hermes-style coding/research agents working in `TomiToivio/LaclauGPT-Data-Collection`.

## Shared contract

Read `AGENTS.md` first. It is the canonical contributor/agent policy. This file only adds Hermes-oriented workflow guidance.

The repository owns reusable data collection only: acquisition, browser/source capture, normalization, provenance, resumability, media references, storage adapters, and scheduling glue. Analysis, codebooks, dashboards, simulation, and private study configuration belong elsewhere.

## Safe workflow

For each task:

1. inspect the current package, tests, and relevant docs;
2. identify the canonical module that should own the behavior;
3. avoid duplicating a legacy subsystem when equivalent functionality already exists;
4. implement against typed public contracts;
5. add synthetic/offline tests;
6. run privacy/publication checks before proposing a merge.

Required checks:

```bash
python scripts/check_public_tree.py
ruff check .
mypy src/laclaugpt_data_collection/config.py \
  src/laclaugpt_data_collection/models.py \
  src/laclaugpt_data_collection/normalize.py \
  src/laclaugpt_data_collection/storage/base.py \
  src/laclaugpt_data_collection/storage/local.py
pytest
```

## Public-repository safety

Never introduce real credentials, cookies, browser state, private endpoints, real monitored account/source lists, raw research data, media, transcripts, exports, machine paths, CSC identifiers, or operational secrets.

When recovering code from private or historical repositories, treat it as untrusted for publication until every path, hostname, identifier, fixture, example, and default has been reviewed. Prefer rewriting a generic interface over copying operational scripts verbatim.

## Architecture rules

- Keep reusable Python code under `src/laclaugpt_data_collection/`.
- Keep browser-extension sources under `browser/`.
- Platform collectors/parsers must not own storage policy.
- Storage adapters must not contain platform-specific parsing.
- Normalization should produce canonical records with stable identifiers and provenance.
- No import-time network calls, model/browser launches, or credential reads with side effects.
- Local filesystem + SQLite operation is the baseline.
- MongoDB, Redis, S3/Allas, browser automation, and feed integrations remain optional.

## Legacy migration rule

Historical repositories are reference implementations, not architecture templates. Classify imported behavior as one of:

- `MIGRATE`
- `ALREADY_IMPLEMENTED`
- `REIMPLEMENT_CLEANLY`
- `OBSOLETE`
- `PRIVATE_OR_OPERATIONAL_DO_NOT_COPY`

Document non-obvious migration choices so future agents do not reintroduce retired code paths.

## Browser/capture rule

Browser capture must remain explicit and privacy-aware. Prefer minimal permissions and local endpoints. Do not silently broaden host permissions, capture scope, or media downloading without documentation, tests, and a clear user-controlled reason.

## Interoperability

Do not make sibling LaclauGPT repositories mandatory dependencies. Exchange data through stable versioned records, JSONL/CSV, storage/service interfaces, or optional adapters.
