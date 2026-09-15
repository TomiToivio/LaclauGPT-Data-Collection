# CyborgAnthropology collection migration

Issue: #11

This is a behavioral migration, not a directory copy. `CyborgAnthropology` is treated as archaeological source code: useful acquisition and normalization ideas are retained, while embedded targets, credentials, operational endpoints, direct MongoDB coupling, and project-specific ideology policy are rejected.

## Migration matrix

| Legacy component | Classification | New home / decision |
|---|---|---|
| `data_collection/mastodon_collector.py` | REIMPLEMENT_CLEANLY | `collectors/mastodon.py`; per-instance Mastodon API, hashtag/public timelines, HTML normalization, account/media/engagement metadata |
| `data_collection/telegram_collector.py` | REIMPLEMENT_CLEANLY | `collectors/telegram.py`; Telethon client is injected, sessions and credentials stay outside Git |
| `data_collection/youtube_collector.py` | REIMPLEMENT_CLEANLY | `collectors/youtube.py`; yt-dlp metadata, transcript API, optional caller-supplied Whisper fallback |
| `data_collection/arxiv_collector.py` | REIMPLEMENT_CLEANLY | `collectors/arxiv.py`; search/category acquisition, bibliographic metadata and PDF reference |
| `data_collection/pdf_collector.py` | REIMPLEMENT_CLEANLY | `collectors/documents.py`; local extraction/chunking only, no Mongo/Chroma coupling |
| `data_collection/x_collector.py` | REIMPLEMENT_CLEANLY / OPTIONAL | `collectors/x_apify.py`; provider acquisition reconciled with existing canonical X/browser parsers |
| `data_collection/rss_collector.py` | ALREADY_COVERED | `collectors/rss.py` |
| `data_collection/bluesky_collector.py` | ALREADY_COVERED | `collectors/bluesky.py` |
| `data_collection/base_collector.py` | MIGRATE BEHAVIOR | Current `Collector`, `CollectionResult`, canonical models, provenance and storage boundaries replace the old base class |
| `data_collection/directory_ingestion.py` | REIMPLEMENT_CLEANLY | `collectors/spool.py`; incoming/processed/error offline spool with canonical validation |
| `data_collection/ingestion.py` | ALREADY_COVERED / SPLIT | canonical capture ingest + storage adapters; Allas upload remains storage boundary |
| `data_collection/firefox/` | ALREADY_COVERED / REPLACED | current privacy-bounded Firefox capture extension |
| `data_collection/data_injection_agent.py` | PROJECT_POLICY | generic schema validation belongs in Collection; AGI relevance lists/research-note heuristics belong in project analysis/policy |
| `data_collection/agi_scraper_agent.py` | PROJECT_POLICY + PRIVATE_DO_NOT_COPY | discovery/orchestration concepts only; hard-coded operational configuration is forbidden from migration |
| `data_collection/redis_settings.py` | DEPRECATED HERE | service configuration belongs to deployment/storage config, not collector source |
| `src/tasks_collection.py` and older scraper task wrappers | DEPRECATED / ORCHESTRATION | invoke public collector APIs from scheduler/agent layers instead of duplicating storage-coupled task functions |
| package boilerplate (`README.md`, `__init__.py`) | DEPRECATED AS CODE SOURCE | documentation only; no behavior to migrate |

## Canonical contract

Every migrated collector emits `NormalizedRecord`, with `source_url` as stable identity. Source-native IDs, author/date/text, source metadata, optional media references, and collection provenance survive the adapter boundary. Raw provider payloads may be retained as provenance metadata when useful, but they are never the primary schema.

## Source-specific behavior preserved

- **Mastodon:** instance URL, toot ID/URL, account identity, HTML-to-text conversion, attachments, favourites/reblogs/replies.
- **Telegram:** channel/message stable URL, channel ID, text and media-presence metadata. Media downloading is an explicit downstream action.
- **YouTube:** video/channel metadata, canonical watch URL, transcript provenance and optional Whisper fallback supplied by deployment code.
- **arXiv:** paper ID, authors, categories, publication/update metadata and PDF reference.
- **X/Apify:** optional account acquisition with engagement/media/raw provider metadata mapped to the same canonical X record shape used by other acquisition paths.
- **Documents:** deterministic `file+sha256:` identity, PDF/text extraction, metadata and reusable chunking without database coupling.
- **Offline/HPC:** directory spool supports local writers and batch jobs without MongoDB, Redis, S3, network access or secrets.

## Dependency policy

Base installation remains small. Mastodon.py, Telethon, yt-dlp, youtube-transcript-api, arxiv, PDF extractors and Apify are optional extras and are imported lazily. Synthetic tests exercise mapping and contracts without those services.

## Privacy and security

Never copy from the historical repository:

- credentials, tokens, phone numbers or session files;
- operational hostnames/endpoints or CSC paths;
- real target/account/channel lists;
- private research data or raw captures;
- project-specific AGI relevance/ideology policy as generic Collection defaults.

The public module accepts these values only through runtime configuration or dependency injection.

## Tests

`tests/test_legacy_collectors.py` verifies Mastodon, Telegram, YouTube, arXiv and X canonical mapping plus document chunking and offline spool round-tripping. Tests assert stable source identity, source metadata, media/provenance retention and zero dependency on external services.
