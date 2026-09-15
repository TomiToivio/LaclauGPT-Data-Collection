# CLAUDE.md

Guidance for Claude Code when working in `TomiToivio/LaclauGPT-Data-Collection`.

## Start here

Read `AGENTS.md` first. It is the shared repository contract for all coding agents and contributors. This file adds Claude-specific operating guidance but does not override `AGENTS.md`, `docs/PRIVACY.md`, or repository CI.

This repository is the canonical reusable **data-collection** module for LaclauGPT. It collects, normalizes, records provenance, and persists source material. It must not absorb discourse analysis, codebooks, visualization, simulation, or study-specific/private research configuration.

## Commands

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

Optional integrations:

```bash
python -m pip install -e '.[distributed]'
python -m pip install -e '.[feeds]'
python -m pip install -e '.[browser]'
```

Useful smoke checks:

```bash
laclaugpt-collect doctor --profile configs/laptop.example.toml
laclaugpt-collect doctor --profile configs/server.example.toml
```

Normal tests must stay offline and must not require platform logins, live scraping, MongoDB, Redis, S3, CSC infrastructure, browser profiles, or credentials.

## Architecture

Canonical Python package:

```text
src/laclaugpt_data_collection/
```

Key boundaries:

- `collectors/`: source/platform acquisition and source-specific parsing
- `models.py`: stable collection/interchange contracts
- `normalize.py`: source payload to canonical record normalization
- `storage/`: persistence adapters only
- `config.py`: public-safe runtime configuration
- `capture.py` / capture service components: browser-assisted capture boundary
- `browser/firefox/`: browser-extension code, kept outside Python package internals

Collectors should emit the canonical normalized record envelope. Downstream LaclauGPT modules should consume that envelope rather than import collector internals.

Do not create a parallel legacy pipeline. When migrating old code, extract reusable behavior into existing modules and document migration decisions.

## Privacy and publication boundary

Treat every commit as immediately public.

Never commit:

- real research data, posts, media, transcripts, screenshots, HAR/PCAP captures, or exports
- account/channel/hashtag/source target lists from actual studies
- cookies, browser profiles, storage state, session tokens, auth headers, API keys, passwords, SSH/OpenStack/S3 credentials
- private endpoints, machine-specific paths, CSC usernames/project numbers, or operational deployment configuration
- copied private-repository material that has not been manually sanitized

Tests and examples must use synthetic data. Placeholder domains such as `example.invalid` and local endpoints such as `127.0.0.1` are preferred.

If sensitive material reaches Git history, deleting it in a later commit is not sufficient. Stop, rotate affected credentials when relevant, and clean history before continuing publication work.

## Browser collection

Browser-assisted capture should be explicit, inspectable, and minimal-permission by default.

- Prefer user-triggered capture over silent broad collection.
- Localhost is the safe default transport target.
- Do not embed credentials or real backend URLs in extension code.
- Keep platform extraction separate from backend normalization/storage.
- Preserve source URL, capture timestamp, provenance, and stable IDs.
- Media download is optional. Metadata collection must work without downloading media.

## Local-first rule

A clean laptop install must remain useful with local files and SQLite. MongoDB, Redis, S3/Allas, Playwright, and feed/browser extras must remain optional.

Do not make another LaclauGPT repository a mandatory runtime dependency. Interoperate via schemas, files, service interfaces, or optional adapters.

## Agent behavior

Before a substantial change:

1. inspect the current implementation and tests;
2. check for an existing canonical abstraction before introducing a new one;
3. preserve privacy/publication constraints;
4. prefer small typed modules over procedural scripts;
5. add or update synthetic tests;
6. run the public-tree guard, lint, relevant type checks, and tests;
7. summarize architectural or migration decisions in docs when behavior came from a legacy repository.

Do not weaken CI, privacy guards, ignore rules, or validation simply to make a change pass.
