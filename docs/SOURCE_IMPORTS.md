# Source Import Map

This cleanup consolidates reusable collection code and patterns while removing unrelated analysis/simulation logic and all private operational material.

## Primary source: LaclauGPT-Discourse-Analysis

Imported/adapted as the architectural core:

- native TikTok/Instagram/X parser model under `collector/modules/`;
- stable normalization/provenance envelope from `collector/normalize.py`;
- browser/network-capture architecture and Firefox-first workflow;
- Bluesky public-XRPC collection pattern;
- separation of raw capture, normalized records, media and collection state.

The original collector explicitly states that collection produces source material and discourse analysis happens later. This repository makes that boundary structural.

## LaclauGPT-TikTok-Scraper

The original scraper is retained as design lineage for TikTok endpoint routing and browser capture. The current TikTok parser is the newer LaclauGPT-native implementation derived from that lineage rather than a wholesale copy of legacy Node/Firefox code.

## CyborgAnthropology

Reusable generic-source concepts are represented as optional adapters for feeds, public web/URL collection and future YouTube/Telegram/arXiv collectors. Analysis and project-specific code are not imported.

## LaclauGPT-Data-Storage

Only backend-integration ideas are used here: records and objects are behind interfaces, with MongoDB/S3 optional. Durable cross-project storage administration remains the responsibility of the Data Storage module.

## LaclauGPT-Social-Simulation-Laboratory

Only collection-worker/browser and scheduling ideas are relevant. Simulation models, agents and scenario logic are excluded.

## LaclauGPT-Discourse-Analysis-Private

Private code was treated as a review source, not as publishable content. Generic ideas retained include:

- laptop collector topology with filesystem/local state;
- server/distributed topology;
- collector-only execution mode;
- legacy generic collector interface patterns.

Real study configuration, account lists, researcher data, machine-specific paths, credentials and anything under private-only boundaries are deliberately not copied.

## Component-level migration map (issue #2, 2026-09-15)

Full audit of `LaclauGPT-Discourse-Analysis/collector/` (~3.5k lines incl. JS)
and `LaclauGPT-TikTok-Scraper`. Classification per the issue: MIGRATE /
ALREADY_IMPLEMENTED / REIMPLEMENT_CLEANLY / OBSOLETE / PRIVATE_OR_OPERATIONAL_DO_NOT_COPY.

| Source component | Classification | Destination |
|---|---|---|
| `collector/modules/{tiktok,instagram,twitter}.py` parsers | MIGRATE (cleanly) | `src/laclaugpt_data_collection/collectors/platforms/` — rewritten against the typed `NormalizedRecord` envelope, parser isolation kept |
| `collector/modules/common.py` | MIGRATE | merged into `collectors/platforms/common.py` + `normalize.py` |
| `collector/backend/records.py` record schema | REIMPLEMENT_CLEANLY | `models.py` `NormalizedRecord` (typed Pydantic, provenance envelope, media references) |
| `collector/backend/normalize_captures.py` | MIGRATE | `collectors/ingest.py` (capture → records, aux families) + `normalize.py` |
| `collector/backend/capture.py` HTTP capture endpoint | MIGRATE | `capture_server.py` (stdlib ThreadingHTTPServer, tour endpoint, account gating) |
| `collector/backend/media.py` + `collector/media.py` | MIGRATE | `media.py` (URL extraction, optional download, checksums, failure recording) |
| `collector/store.py` (raw/normalized/manifests + SQLite state) | MIGRATE | `store.py` `CollectionStore` (raw append, upsert dedup, checkpoints/cursors, media index) + `storage/` adapters |
| `collector/backend/scheduler.py` | REIMPLEMENT_CLEANLY | job state lives in `store.py` checkpoints/cursors; scheduling stays external (cron/worker) by design — no in-process scheduler |
| `collector/run.py` collection runner | PARTIALLY MIGRATE | window gating + account tours in `capture_server.py`/`study.py`; CLI orchestration in `cli.py` |
| `collector/config.py` + `config/STUDY_TEMPLATE.yaml` | MIGRATE | `study.py` (StudyConfig, handle validation, window/timezone); real target lists stay in ignored local files |
| `collector/bluesky.py` | MIGRATE | `collectors/bluesky.py` (public XRPC) |
| `collector/normalize.py` | MIGRATE | `normalize.py` (+ aux-family normalization for TikTok comment/user/challenge salvage) |
| `collector/browser.py` CDP/agent-browser drivers | OBSOLETE for this repo (deliberate) | CDP path produced empty response bodies in practice; the Firefox-first policy (extension → local capture backend) replaces it. Not migrated. |
| `collector/browser/` extension (MV2 + modules JS) | MIGRATE | `browser/firefox/` (capture.js, content.js, navigation.js); platform modules inlined into capture.js matchers |
| `collector/firefox/extension/` | DUPLICATE of above | superseded by `browser/firefox/`; not copied again |
| TikTok-Scraper `Firefox/*` | SALVAGE | legacy hard-coded target lists in content.js deliberately NOT carried over (sensitive operational config); response-interception pattern + comment/user/challenge endpoint families live on (`tiktok_extras.py`, AUX_PARSERS) |
| TikTok-Scraper `Node/index.js` | OBSOLETE | Node capture pipeline superseded by the Python backend + extension |
| CyborgAnthropology generic source adapters | REIMPLEMENT_CLEANLY | `collectors/rss.py` (+ future feed adapters behind the Collector protocol) |
| Private repo operational configs | PRIVATE_OR_OPERATIONAL_DO_NOT_COPY | nothing copied; study configs synthetic only |

Migration principle applied: prefer the cleaner destination architecture
wherever equivalent functionality already exists; no duplicate
implementations were created for logic present in both historical trees.

## Rule for future imports

Before copying code from another LaclauGPT repository:

1. verify the code is genuinely collection-related;
2. verify license/provenance;
3. remove project-specific paths, targets and credentials;
4. convert configuration to environment/example configuration;
5. make emitted records comply with the interoperability schema;
6. add synthetic tests;
7. document the import here.
