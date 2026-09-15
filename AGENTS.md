# Agent and Contributor Rules

This repository is public-safe infrastructure. Treat every commit as if it will be published immediately.

## Scope

Only add code directly required for data collection:

- source/browser/network capture;
- platform/source parsers;
- normalization and provenance;
- collection state and resumability;
- raw/media persistence;
- source scheduling/worker glue;
- backend adapters and interoperability schemas.

Do **not** add discourse analysis, LLM analysis, dashboards, simulations, researcher reports, codebooks or project-specific datasets here.

## Privacy rules

Never commit secrets, real credentials, cookies, browser profiles, private endpoints, study/account target lists, raw research data, media, exports or real operational config.

Use environment variables for secrets. Checked-in config must be schema/example/synthetic only. Never add a real `.env` file.

Before committing copied code from a private repository, manually review every line and remove paths, identifiers, hostnames, account names, credentials and data samples. Prefer reimplementing a generic interface over copying private operational files.

If restricted material enters Git history, stop publication work, rotate credentials if applicable, and rewrite history. A later deletion commit is not sufficient.

## Architecture

Use the `src/laclaugpt_data_collection/` package. Keep imports acyclic and backend-neutral.

Collectors emit `NormalizedRecord`. Downstream LaclauGPT modules depend on the stable record envelope, not collector internals.

Local mode must remain usable with filesystem + SQLite and without MongoDB, Redis, S3 or browser extras installed.

Distributed integrations are optional extras. Prefer MongoDB for records, Redis for coordination/cache, and S3-compatible storage (including CSC Allas) for raw/media objects.

## Python practices

- Python >= 3.11.
- Type public APIs.
- Use `pathlib`, context managers and standard logging.
- Keep side effects out of imports.
- Lazy-import optional dependencies.
- No hard-coded machine paths or credentials.
- Small modules with single responsibilities.
- Synthetic tests for parsers and storage adapters.
- `ruff check .`, `ruff format --check .`, and `pytest` must pass before merge.

## Interoperability

Do not make another LaclauGPT module a mandatory dependency. Communicate through versioned schemas, JSONL/CSV exports, storage/service interfaces or explicit optional integrations.
