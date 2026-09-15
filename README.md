# LaclauGPT Data Collection

[![CI](https://github.com/TomiToivio/LaclauGPT-Data-Collection/actions/workflows/ci.yml/badge.svg)](https://github.com/TomiToivio/LaclauGPT-Data-Collection/actions/workflows/ci.yml)

Public, reusable data-collection module for the LaclauGPT ecosystem.

This repository contains **collection, capture, normalization, provenance and storage-adapter code only**. Analysis, simulation, dashboards, research datasets, operational target lists, credentials and machine-specific secrets belong elsewhere.

## Design goals

- Python `src/` layout with a small typed package and CLI.
- Local-first defaults: filesystem + SQLite + CSV/JSONL work without external services.
- Distributed deployment when configured: MongoDB for records, Redis for coordination/cache, and S3-compatible object storage such as CSC Allas for raw/media objects.
- Explicit interoperability contract with LaclauGPT Data Storage, Data Analysis, Data Visualization, Research Assistant and Simulation modules.
- Provenance-first collection. Normalized records retain stable IDs and references to source/raw capture metadata.
- Public-repository hygiene: no research data, target/account lists, browser profiles, cookies, tokens, credentials or real deployment configuration in Git.

## Lineage and imports

The architecture primarily consolidates the reusable `collector/` subsystem from `TomiToivio/LaclauGPT-Discourse-Analysis`, including its native TikTok/Instagram/X parser design, normalization/provenance model, Firefox/browser capture approach and Bluesky public-API collector.

Additional reusable ideas/code paths are consolidated from:

- `TomiToivio/LaclauGPT-TikTok-Scraper` — TikTok request routing and Firefox capture lineage.
- `TomiToivio/CyborgAnthropology` — generic collector patterns and RSS/YouTube/Telegram/arXiv source adapters.
- `TomiToivio/LaclauGPT-Data-Storage` — storage/service integration patterns.
- `TomiToivio/LaclauGPT-Social-Simulation-Laboratory` — generic URL/browser collector and scheduling/worker patterns.
- `TomiToivio/LaclauGPT-Discourse-Analysis-Private` — only reusable, non-sensitive collector/runtime ideas; **no private configuration or data is copied**.

See `docs/SOURCE_IMPORTS.md` for boundaries and provenance.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Optional distributed backends:

```bash
python -m pip install -e '.[distributed]'
```

## Configuration

Configuration is environment-driven. The checked-in files under `configs/` are **examples only**.

```bash
cp .env.example .env
# edit locally; .env is ignored by Git
```

Local laptop defaults:

```bash
laclaugpt-collect doctor --profile configs/laptop.example.toml
```

Server/distributed example:

```bash
laclaugpt-collect doctor --profile configs/server.example.toml
```

The application never requires a checked-in private config file. Real target lists, credentials, machine paths and deployment settings belong in environment variables, ignored local files, private operational repositories or secret-management systems.

## Storage modes

### Default: local

- metadata/state: SQLite
- tabular/interchange output: JSONL/CSV
- raw payloads/media: local filesystem
- queue/cache: in-process/no Redis required

### Distributed

- records/metadata: MongoDB
- coordination/cache: Redis
- objects/raw/media: S3-compatible storage (CSC Allas works through its S3 API)

Backends are selected independently so hybrid deployments are possible.

## Interoperability contract

Every normalized record uses a stable envelope:

```json
{
  "schema_version": "1.0",
  "document_id": "platform-stable-id",
  "platform": "tiktok",
  "author": "example",
  "timestamp": "2026-09-15T12:00:00Z",
  "source_url": "https://example.invalid/post/1",
  "text": "synthetic example",
  "media_references": [],
  "raw_ref": "objects/raw/...",
  "collection_provenance": {
    "collector": "laclaugpt-data-collection",
    "collector_version": "0.1.0",
    "capture_id": "...",
    "run_id": "..."
  }
}
```

Downstream modules should consume this envelope rather than collector-internal classes.

## Privacy and public-repo rules

Read `docs/PRIVACY.md` before adding any source, configuration or fixture. The repository is intended to remain public-safe at every commit, not merely after cleanup.

1. Never commit `.env`, cookies, browser profiles, HAR/PCAP captures, tokens, passwords, API keys, private URLs, CSC/OpenStack credentials, SSH material, infrastructure state or real deployment configs.
2. Never commit collected research data, downloaded media, raw API responses, researcher exports or real participant/account/channel target lists.
3. Real machine/server configuration belongs outside Git. Checked-in configuration must be an explicitly named example/schema containing placeholders only.
4. Tests and fixtures must be synthetic and must not be lightly edited copies of real research material.
5. CI runs a public-tree scanner that rejects common private/data artifacts, literal secrets and credential-bearing URLs.
6. If a secret or restricted dataset is ever committed, treat it as compromised: rotate/revoke it and rewrite Git history. A later deletion commit is not sufficient.

Run the required publication checks locally with:

```bash
python scripts/check_public_tree.py
ruff check .
mypy src/laclaugpt_data_collection
pytest
```

`ruff format .` is recommended whenever touching Python files. Some imported legacy modules are being normalized incrementally, so formatting is not yet a repository-wide CI gate.

## Development

```bash
python -m pip install -e '.[dev]'
python scripts/check_public_tree.py
ruff check .
mypy src/laclaugpt_data_collection
pytest
```

The repository uses a narrow package surface: collectors emit normalized records; storage adapters persist them; orchestration composes the two. Analysis belongs in `LaclauGPT-Data-Analysis`, not here.
