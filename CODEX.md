# CODEX.md

Guidance for Codex and other autonomous coding agents working in `TomiToivio/LaclauGPT-Data-Collection`.

## Canonical policy

Read `AGENTS.md` first. It is the shared repository contract. Also read `docs/PRIVACY.md` before touching configuration, fixtures, browser capture, storage, or migrated legacy code.

This repository is the canonical reusable collection layer for LaclauGPT. Keep its responsibility narrow: source acquisition, browser/source capture, normalization, provenance, collection state/resumability, media references, storage adapters, and scheduling/worker glue.

Do not add discourse-analysis logic, codebooks, LLM interpretation, dashboards, simulations, researcher reports, or real study configuration.

## Development checks

```bash
python -m pip install -e '.[dev]'
python scripts/check_public_tree.py
ruff check .
mypy src/laclaugpt_data_collection/config.py \
  src/laclaugpt_data_collection/models.py \
  src/laclaugpt_data_collection/normalize.py \
  src/laclaugpt_data_collection/storage/base.py \
  src/laclaugpt_data_collection/storage/local.py
pytest
```

Use `ruff format .` for touched Python files when appropriate.

## Implementation rules

- Work inside the existing `src/` architecture instead of adding new top-level procedural pipelines.
- Reuse canonical models and normalization before inventing new record shapes.
- Keep platform-specific code isolated from common storage and normalization.
- Keep optional dependencies lazy and behind extras.
- No network activity, browser launch, or expensive initialization at import time.
- Keep local filesystem + SQLite usable without external infrastructure.
- Preserve stable IDs, source URLs, capture timestamps, provenance, and idempotent re-ingestion semantics where possible.
- Prefer explicit exception types and logging over broad silent failure.

## Privacy

Assume every branch and commit can become public immediately.

Never commit real datasets, media, transcripts, screenshots, browser/network captures, cookies, sessions, target lists, credentials, private endpoints, deployment secrets, CSC identifiers, or machine-specific paths. Synthetic fixtures only.

Do not weaken `.gitignore`, the public-tree scanner, privacy tests, or CI to make a feature easier to land.

## Legacy code

When using `LaclauGPT-Discourse-Analysis`, `LaclauGPT-TikTok-Scraper`, private repositories, or older collector code as references, extract behavior rather than copying directory structure. Document migration status and deliberately retired behavior.

## Pull requests

A good PR should be small enough to review, explain why the chosen module owns the behavior, include synthetic tests, preserve local-first behavior, and call out any optional/distributed dependencies or privacy implications.
