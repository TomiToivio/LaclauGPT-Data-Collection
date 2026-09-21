# LaclauGPT Data Collection

[![CI](https://github.com/TomiToivio/LaclauGPT-Data-Collection/actions/workflows/ci.yml/badge.svg)](https://github.com/TomiToivio/LaclauGPT-Data-Collection/actions/workflows/ci.yml)

> **Part of the [LaclauGPT](https://github.com/TomiToivio/LaclauGPT) project.** The main LaclauGPT repository is the **meta-repository** and project front door: it contains the scientific paper, theory, shared architecture, canonical data contract and complete-system documentation. This repository is only the **Data Collection** implementation stage.
>
> **Project map:** [LaclauGPT / paper + meta-repo](https://github.com/TomiToivio/LaclauGPT) → **Data Collection (you are here)** → [Data Analysis](https://github.com/TomiToivio/LaclauGPT-Data-Analysis) → [Data Visualization](https://github.com/TomiToivio/LaclauGPT-Data-Visualization)

**LaclauGPT** is an open social-science research framework for **LLM-assisted computational discourse analysis** of large textual and multimodal corpora. It combines computational methods with interpretive political research while keeping model outputs traceable to source evidence, uncertainty, provenance and human review.

The current flagship research programme is **[LaclauGPT: Ideological contestation over AI](https://github.com/TomiToivio/LaclauGPT/blob/main/paper/PHASE_1_PAPER.md)**. The canonical theoretical and methodological contract is **[THEORY.md](https://github.com/TomiToivio/LaclauGPT/blob/main/THEORY.md)**.

The framework is developed around Ernesto Laclau and Chantal Mouffe's discourse theory and Emilia Palonen's work on populism, polarisation and hegemonic dynamics. The AI/AGI study is the main development case, but LaclauGPT is a **general research framework rather than a single-purpose AI classifier**. The same architecture can support election research, populism, grievance politics, social-media research and other comparative discourse-analysis projects.

> [!WARNING]
> **Human-in-the-loop academic research only.** LaclauGPT's machine-generated summaries, classifications, discourse-theoretical codes, signifier roles, ideological formations, affects and other interpretations are preliminary analyses that must be verified by a human researcher. They are not ground truth or autonomous scholarly judgement. LaclauGPT is designed for academic research, not autonomous operational, administrative, intelligence, moderation, profiling or policy decisions about people or groups.


<!-- project-background:start -->
## Project background and funding

LaclauGPT grew out of research-software work at the **[Helsinki Hub on Emotions, Populism and Polarisation (HEPP)](https://www.helsinki.fi/en/researchgroups/emotions-populism-and-polarisation), University of Helsinki**, and the **2024 European Parliament election (EP24)** research programme. The EP24 pipeline collected and analysed multimodal TikTok and Instagram material across multiple European countries; the current modular LaclauGPT framework generalises that work into reusable Data Collection, Data Analysis and Data Visualization components.

The software has been developed in connection with three international research projects supported by the **European Union** and the **Research Council of Finland / Academy of Finland**. The project logos below link to the official project pages.

<p align="center">
  <a href="https://www.co3socialcontract.eu/" title="CO3 — Continuous Construction of Resilient Social Contracts Through Societal Transformations">
    <img src="https://www.helsinki.fi/assets/drupal/styles/16_10_fallback/s3/media-image/co3_rgb%20%281%29.jpg.jpeg?itok=2G8xjx4J" height="92" alt="CO3 project logo">
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://www.endure-project.org/" title="ENDURE — Inequalities, Community Resilience and New Governance Modalities in a Post-Pandemic World">
    <img src="https://www.endure-project.org/favicon.ico" height="72" alt="ENDURE project logo">
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://www.pledgeproject.eu/" title="PLEDGE — Politics of Grievance and Democratic Governance">
    <img src="https://cdn.myportfolio.com/80780752-1793-414b-936a-f0cd10a2ac7d/57c00d24-bb6a-4af2-a001-c65a765651f9_rw_1920.png?h=41199a43847532a5a8800551fe811ed5" height="92" alt="PLEDGE project logo">
  </a>
</p>

- **[CO3 — Continuous Construction of Resilient Social Contracts Through Societal Transformations](https://www.co3socialcontract.eu/)** studies more democratic, inclusive and resilient social contracts. It is funded by the European Union's Horizon Europe programme under grant agreement **No. 101132631**.
- **[ENDURE — Inequalities, Community Resilience and New Governance Modalities in a Post-Pandemic World](https://www.endure-project.org/)** examined inequalities, community resilience and governance after COVID-19. It was funded through the **Trans-Atlantic Platform (T-AP) Recovery, Renewal and Resilience** call; Finnish participation was supported by the Academy of Finland / Research Council of Finland.
- **[PLEDGE — Politics of Grievance and Democratic Governance](https://www.pledgeproject.eu/)** studies the emotional dynamics of political grievances and democratic governance. It is funded by the European Union's Horizon Europe programme under grant agreement **No. 101132560**.

LaclauGPT is open research software. References to these projects describe the research and funding context in which the software has been developed; they do not imply that every current LaclauGPT research question or software component is a deliverable of each project.

<!-- project-background:end -->

## Research philosophy: human-in-the-loop as an assemblage

LaclauGPT uses a deliberately assemblage-based working philosophy of AI:

> **AI = HUMAN + LLM + LANGUAGE + INTERNET**

This is a methodological and philosophical framing, not a settled empirical claim about machine consciousness.

- **HUMAN — interpretation and accountable agency.** Researchers choose questions, define concepts and codebooks, evaluate evidence, resolve ambiguity and remain responsible for conclusions.
- **LLM — learned model plus agentic machinery.** Models may contribute structured proposals, retrieval, comparison and tool use, but their outputs remain fallible and provisional.
- **LANGUAGE — communication protocol and cognitive medium.** Language couples the researcher, model, sources and theoretical concepts, and helps structure the distinctions and relations available to analysis.
- **INTERNET — infrastructure and epistemic environment.** Networks, software, model repositories, databases, APIs and research corpora form part of the practical research system. Retrieved information remains evidence to evaluate.

Human-in-the-loop therefore means more than a final approval step. The human researcher is constitutive of the research process throughout.

## Theoretical and methodological orientation

LaclauGPT treats political meaning as relational, contested and only partially fixed. The system is designed to investigate articulations among actors, demands, identities, signifiers and political frontiers rather than reducing discourse to keywords, topics or sentiment.

Its theoretical concepts include nodal points, floating and empty signifiers, equivalence and difference, collective subjects, antagonistic frontiers, affective investment, ideological formations, myths, imaginaries and hegemonic dynamics. These are evidence-supported analytical roles, not automatic labels.

Important cautions include: **frequency is not hegemony; semantic similarity is not equivalence; negative sentiment is not antagonism; polysemy is not empty signification; and document-level evidence does not automatically establish corpus-level formations.** Abstention is a valid output when evidence is insufficient.

See the **[scientific paper](https://github.com/TomiToivio/LaclauGPT/blob/main/paper/PHASE_1_PAPER.md)** and **[theory contract](https://github.com/TomiToivio/LaclauGPT/blob/main/THEORY.md)** for the full conceptual framework.

## This repository

**LaclauGPT Data Collection** is the public, reusable data-acquisition layer of the LaclauGPT ecosystem. This repository contains **collection, capture, normalization, provenance, scheduling and storage-adapter code only**. It prepares auditable source material for later analysis without performing discourse-theoretical interpretation itself.

Its output is the shared canonical record consumed by **[LaclauGPT Data Analysis](https://github.com/TomiToivio/LaclauGPT-Data-Analysis)** and ultimately inspected in **[LaclauGPT Data Visualization](https://github.com/TomiToivio/LaclauGPT-Data-Visualization)**. Project-wide contracts and the scientific rationale belong in the **[LaclauGPT meta-repository](https://github.com/TomiToivio/LaclauGPT)**.

Analysis, simulation, dashboards, research datasets, operational target lists, credentials and machine-specific secrets belong elsewhere.

## Design goals

- Python `src/` layout with a small typed package and CLI.
- One canonical implementation across researcher laptops, Linux servers and agent operation.
- Local-first defaults: filesystem + SQLite + CSV/JSONL work without external services.
- Distributed deployment when configured: MongoDB for records, Redis for coordination/settings/task queues/messaging, and S3-compatible object storage such as CSC Allas for raw/media objects.
- Canonical `source_url` or stable URI-like identity across every backend and module handoff.
- Public-repository hygiene: no research data, target/account lists, browser profiles, cookies, tokens, credentials or real deployment configuration in Git.

## Phase 1 runtime and legacy Phase 0 compatibility

> [!IMPORTANT]
> **Current development phase: Phase 1.** `phase-1` is the canonical active development/stable phase branch, and `main` MUST match its current validated state. The `phase-0` branch is a preserved legacy baseline only. New unphased work defaults to Phase 1; Phase 2–4 remain isolated until explicitly promoted.

Phase 1 is now the active repository state. The narrow Phase 0 RSS/Atom path below is retained only as a compatibility baseline and rollback reference while Phase 1 capabilities are restored incrementally:

```text
RSS/Atom feeds -> canonical text records -> MongoDB -> Data Analysis
```

The `laclaugpt-server-rss` entry point is now the bounded Phase 1 Laskin RSS worker. It reads `[[feed]]` rows from the source manifest and writes through the same canonical `DistributedCaptureSink` used by browser capture, so unattended RSS and localhost browser records share the project-scoped `<project>__records` collection. The older flat Phase 0 helpers remain available as compatibility code and tests, but they are no longer the Laskin cron path.

Example Phase 1 invocation:

```bash
LACLAUGPT_PROJECT_ID=ai26 \
laclaugpt-server-rss \
  --study-config data/config/ai26.yaml \
  --source-manifest data/config/ai26.sources.toml \
  --max-feeds 8 \
  --per-feed-limit 5 \
  --limit 40
```

On Laskin, `scripts/run_ai26_laskin_collect.sh` remains the bounded one-cycle cron wrapper and explicitly refuses browser-enabled runtime configuration. Phase 0 storage adapters remain documented below only for compatibility and rollback work.

### Phase 0 MongoDB boundary (shared with Data Analysis)

Phase 0 collection and the Phase 0 analysis core share **one** database and **one** collection name. The collection is derived from the project id:

```text
laclaugpt2_<project>_scraper_collection      # e.g. laclaugpt2_ai26_scraper_collection
```

This is deliberately **not** the Phase 1 distributed collection naming (`<project>__records`). Phase 1 writes nested `CanonicalRecord` documents; the hand-coded Phase 0 analysis core reads flat documents. `src/laclaugpt_data_collection/phase0_mongo.py` is the explicit Phase 0 adapter between the two and can be retired once Phase 1 is reintroduced step by step.

The flat document exposes the fields analysis expects:

```text
document_id, source_url, source_text, source_title, source_date, source_name,
source_type, source_feed_url, source_author, source_categories, content_hash,
project, arena, actor_name, actor_type, ai_formation, political_formation,
country, language, site_name, collected_at
```

Two properties make the boundary safe to run from cron:

- **Identity.** Documents are upserted on the canonical `source_url` (fragments and tracking parameters such as `utm_*`/`fbclid` stripped), so re-collecting an article updates it instead of creating a duplicate the analysis core would analyse twice.
- **Minimality.** The Phase 0 path requires MongoDB only. It opens no Redis connection and no S3/Allas connection, and the existing Phase 1 distributed runner is left intact for later restoration.

The boundary is pinned by `tests/test_issue_85_phase0_mongo_contract.py`, which asserts the collection name and required field list against the constants the analysis core uses.


## Source-plugin architecture

Collection now has a versioned source-plugin layer around the existing collectors. The architecture is intentionally simple:

```text
SOURCE PLUGINS -> CANONICAL RECORD -> DURABLE STORAGE -> DATA ANALYSIS
```

The "WordPress for social data science" analogy means modular plugin contracts and interoperability. It does **not** merge Collection, Analysis and Visualization into one runtime. Collection can continue running independently on Linux servers and researcher laptops while Analysis runs on suitable GPU/compute infrastructure and Visualization runs locally or on a web server.

`PluginSpec` declares plugin ID/version, source type, configuration schema, authentication, execution modes, retry/identity/raw/media policies and scheduling expectations. `adapt_collector()` wraps existing `Collector.collect()` implementations, while `CollectionRunner` writes canonical records to backend-neutral durable storage before any optional Redis/event notification.

The first incrementally migrated built-ins are RSS and Bluesky; the same adapter is intended for Mastodon, YouTube, Telegram, arXiv, browser-assisted collectors and future external packages.

Inspect the built-in contract without contacting source services:

```bash
laclaugpt-collect plugins list
```

See [`docs/PLUGIN_ARCHITECTURE.md`](docs/PLUGIN_ARCHITECTURE.md) for the plugin API, scheduling model, identity/deduplication rules, media boundary, privacy propagation and Data Analysis handoff.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

The `dev` extra is the supported contract for running the full test suite. It includes the test-time RDF/SHACL dependencies used by the knowledge-graph tests. Install the separate `kg` extra when developing or running the optional knowledge-graph backends themselves.

Optional distributed backends:

```bash
python -m pip install -e '.[distributed]'
```

## Deployment profiles

Machine, execution, browser and storage are independent configuration dimensions. See [`docs/DEPLOYMENT_AND_HERMES.md`](docs/DEPLOYMENT_AND_HERMES.md) and [`docs/TWO_MACHINE_SETUP.md`](docs/TWO_MACHINE_SETUP.md) for the manual-researcher-host + cron-collector-host pattern.

Researcher laptop with Firefox capture:

```bash
laclaugpt-collect doctor --profile configs/laptop.example.toml
```

Linux server with local SQLite/filesystem storage:

```bash
laclaugpt-collect doctor --profile configs/server-local.example.toml
```

Linux server with MongoDB + Redis + S3/CSC Allas:

```bash
laclaugpt-collect doctor --profile configs/server.example.toml
```

Generate scheduling examples without modifying cron or systemd:

```bash
laclaugpt-collect schedule cron --command-line "laclaugpt-collect doctor --profile data/config/server.toml"
laclaugpt-collect schedule systemd --command-line "laclaugpt-collect doctor --profile data/config/server.toml"
```

Real target lists, credentials, machine paths and operational schedules belong under ignored `data/`, private operational repositories, environment variables or secret-management systems.

## Storage modes

Local/default:

- canonical records/state: SQLite
- tabular/manual interchange: JSONL/CSV/Pandas-compatible files
- raw payloads/media: local filesystem under `data/`
- coordination/cache: in-process, no Redis required

Distributed:

- canonical records: MongoDB
- coordination/settings/task queues/messaging: Redis
- objects/raw/media: S3-compatible storage such as CSC Allas

Backends are selected independently, so a Linux server may still use SQLite and local files. Redis is infrastructure, not the research-data schema. Backend-specific IDs never replace `source_url`.

When Collection and Analysis run on the same machine, Analysis may read the configured Collection `data/` tree directly. CSV/JSONL remains the manual handoff fallback.

## Canonical record contract

Collection populates the source-side sections of the project-wide canonical record. A simplified example is:

```json
{
  "schema_version": "1.0.0",
  "source_url": "https://example.invalid/post/1",
  "source_native_ids": {"document_id": "platform-stable-id"},
  "source": {
    "platform": "tiktok",
    "author": "example",
    "created_at": "2026-09-15T12:00:00Z",
    "collection_method": "browser-extension",
    "raw_ref": "raw/tiktok/example.ndjson"
  },
  "content": {
    "text": "synthetic example",
    "media_references": []
  },
  "provenance": []
}
```

`NormalizedRecord` remains only a compatibility constructor for older collectors. Persisted output uses the canonical nested record. See [`docs/CANONICAL_RECORD.md`](docs/CANONICAL_RECORD.md).

## Firefox-assisted capture

The Firefox workflow captures supported public platform response bodies and embedded public page state into a localhost backend. The default backend binds to `127.0.0.1:8765`; `firefox-local` configuration is rejected if it attempts a non-loopback bind.

See [`docs/BROWSER_CAPTURE.md`](docs/BROWSER_CAPTURE.md) and [`docs/EXTENSION_PRIVACY.md`](docs/EXTENSION_PRIVACY.md). Browser capture remains researcher-controlled and does not carry credentials or target lists in the extension source.

## Hermes agent operation

Hermes uses the same Settings, canonical record, collector and storage APIs as the CLI. The reusable integration surface is `laclaugpt_data_collection.integrations.hermes`, and the agent skill is [`skills/laclaugpt-data-collection/SKILL.md`](skills/laclaugpt-data-collection/SKILL.md).

Agent inspection and dry-run operations are redacted and offline. Agent-triggered canonical records can be stamped with caller metadata such as `hermes-agent`; agent operation does not create a second schema or collector pipeline.

## Lineage and imports

The architecture consolidates reusable Collection behavior from `TomiToivio/LaclauGPT-Discourse-Analysis`, the historical TikTok Firefox scraper lineage, selected generic collection patterns from `TomiToivio/CyborgAnthropology`, and storage/scheduling ideas from related LaclauGPT repositories. Historical repositories are reference implementations, not architecture templates.

See [`docs/SOURCE_IMPORTS.md`](docs/SOURCE_IMPORTS.md) and [`docs/COLLECTOR_MIGRATION.md`](docs/COLLECTOR_MIGRATION.md) for migration boundaries and provenance.

## Privacy and public-repo rules

Read [`docs/PRIVACY.md`](docs/PRIVACY.md) before adding any source, configuration or fixture. The repository is intended to remain public-safe at every commit.

Never commit `.env`, cookies, browser profiles, HAR/PCAP captures, tokens, passwords, API keys, private URLs, CSC/OpenStack credentials, SSH material, infrastructure state, collected research data, downloaded media, raw API responses, researcher exports, or real participant/account/channel target lists. Tests and examples use synthetic content only.

All runtime and study-specific material belongs under the ignored repository-local `data/` tree or external private infrastructure. See [`docs/RUNTIME_DATA.md`](docs/RUNTIME_DATA.md).

Run the required publication checks locally with:

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

The mypy gate covers the stable interoperability/configuration/storage core. Imported platform parsers retain some legacy typing debt and are covered by linting and functional tests.

## Development

The repository uses a narrow package surface: collectors emit canonical records, storage adapters persist them, and orchestration composes the two. Analysis belongs in **[LaclauGPT-Data-Analysis](https://github.com/TomiToivio/LaclauGPT-Data-Analysis)**; researcher-facing dashboards belong in **[LaclauGPT-Data-Visualization](https://github.com/TomiToivio/LaclauGPT-Data-Visualization)**; paper/theory and cross-module architecture belong in **[LaclauGPT](https://github.com/TomiToivio/LaclauGPT)**.
