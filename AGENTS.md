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

Use environment variables for secrets. Checked-in config must be schema/example/synthetic only. Never add a real `.env` file. Real machine/server profiles, target lists and deployment credentials belong in ignored local files, private operations repositories or secret-management systems.

Before committing copied code from a private repository, manually review every line and remove paths, identifiers, hostnames, account names, credentials and data samples. Prefer reimplementing a generic interface over copying private operational files.

If restricted material enters Git history, stop publication work, rotate credentials if applicable, and rewrite history. A later deletion commit is not sufficient. Also inspect pull-request refs and cached commit views before considering the repository clean.

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
- `python scripts/check_public_tree.py`, `ruff check .`, the stable-core mypy check in CI, and `pytest` must pass before merge.
- Do not silence legacy parser typing debt with broad `# type: ignore` directives. Improve those modules incrementally.
- Use `ruff format .` when editing Python code; formatting modernization may be applied incrementally to legacy imported modules.

## Interoperability

Do not make another LaclauGPT module a mandatory dependency. Communicate through versioned schemas, JSONL/CSV exports, storage/service interfaces or explicit optional integrations.

## Canonical record contract

All collectors and storage adapters must use the canonical source contract: `source_url`/URI is the semantic identity when available; platform-native IDs are aliases; backend row/object IDs must not become downstream identities. Preserve schema version, provenance, timestamps, lists and media references across JSONL, CSV, SQLite and remote adapters.
