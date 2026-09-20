# Collection plugin architecture

LaclauGPT Data Collection is the acquisition-side half of the broader modular social-data-science architecture. The "WordPress" analogy means **stable plugin contracts and interoperability**, not collapsing Collection, Analysis and Visualization into one process or repository.

```text
[RSS] --------\
[Bluesky] -----\
[Mastodon] ------> COLLECTION PLUGIN INTERFACE
[YouTube] -------/            |
[Browser] ------/             v
                     CANONICAL RECORD
                            |
                  +---------+---------+
                  |                   |
             CSV/SQLite/files       MongoDB
                  |                   |
                  +---------+---------+
                            |
                            v
                     DATA ANALYSIS
```

The boundary is deliberately strict:

```text
Data Collection: SOURCE -> CANONICAL RECORD -> DURABLE STORAGE
Data Analysis:   CANONICAL RECORD -> PREPROCESS -> ANALYSIS -> POSTPROCESS
```

Collection preserves source facts, source-native relationships, raw payloads or durable raw references, media references, collection provenance and project routing metadata. It does not infer discourse roles, ideology, hegemony, sentiment, topics or other social-science interpretations.

## Versioned plugin contract

`laclaugpt_data_collection.plugins.PluginSpec` declares the stable public metadata for a collector:

- unique `plugin_id` and plugin `version`;
- `source_type`;
- JSON-Schema-like `config_schema` declaration;
- authentication expectations;
- supported execution modes (`polling`, `streaming`, `manual`, `batch`, `webhook`);
- retry/rate-limit expectations;
- canonical identity strategy;
- raw-payload and media policies;
- scheduling expectations.

`CollectionPlugin.collect(context)` returns the existing `CollectionResult`, whose records are canonical `NormalizedRecord`/`CanonicalRecord` objects. Existing collectors do not need rewrites: `adapt_collector(spec, factory)` wraps the current `Collector.collect()` interface.

The Phase 1 built-in registry includes RSS, Bluesky, Mastodon, Telegram and arXiv. YouTube, browser-assisted sources and other existing collectors can move behind the same adapter incrementally without changing the three-module deployment architecture.

Inspect the currently registered declarations without contacting source services:

```bash
laclaugpt-collect plugins list
```

## Writing a plugin

A plugin should keep source-specific behavior at the edge and emit the canonical record as early as practical.

```python
from laclaugpt_data_collection.plugins import (
    CollectionContext,
    PluginSpec,
    adapt_collector,
)

spec = PluginSpec(
    plugin_id="example",
    version="1.0.0",
    source_type="example-api",
    config_schema={
        "type": "object",
        "required": ["endpoint"],
        "properties": {"endpoint": {"type": "string"}},
    },
    modes=("polling", "batch"),
)


def factory(context: CollectionContext):
    endpoint = str(context.require("endpoint"))
    return ExistingExampleCollector(endpoint=endpoint)


plugin = adapt_collector(spec, factory)
```

The adapter stamps records with plugin ID/version, run ID, collection/project routing metadata and project privacy metadata in collection provenance. This avoids inventing a second persistent schema.

## Canonical identity and deduplication

Every logical record must have a stable `source_url` or URI-like source identifier. Examples include normal web URLs, `at://...`, Telegram/message identifiers, arXiv identifiers and deterministic import URNs.

`CollectionRunner` checks `RecordStore.contains(source_url)` before writing. Repeated cron-style execution therefore skips already persisted logical records. Mutable source observations can still be explicitly versioned by source-specific collectors or storage policies when a project needs snapshots over time.

Database row IDs, Mongo `_id` values and local filenames are backend details and never cross-module identities.

## Durable storage before events

`CollectionRunner` enforces this ordering:

```text
collect
  -> normalize canonical record
  -> durable RecordStore.upsert(record)
  -> optional notifier / Redis / queue event
```

Messaging is therefore coordination only. Redis is optional and must never be the sole copy of collected research material.

The same runner contract works with local SQLite/file-backed stores or configured MongoDB-backed stores. Large raw/media objects may live on the local filesystem or S3-compatible storage such as CSC Allas and remain referenced from the canonical record.

## Scheduling and deployment

Plugins contain no hard-coded schedule. Cadence belongs in private project/deployment configuration.

Typical server scheduling remains lightweight:

```text
*/5 * * * *  collect rss
*/10 * * * * collect bluesky
0 * * * *    collect youtube
```

The framework supports independent deployments:

- Linux/server collectors via cron, systemd or long-running workers;
- researcher-laptop CLI runs;
- browser-assisted/manual collectors where interactive authentication is required;
- optional distributed coordination when configured.

Collection remains independently deployable from GPU-heavy Data Analysis and from the Visualization/Research UI.

## Raw source data, relationships and media

Plugins should preserve source-native data whenever legally and ethically appropriate:

- raw payload inline or an immutable `raw_ref`;
- reply/repost/quote/thread/conversation identifiers;
- mentions, links, hashtags and channel/account identifiers;
- engagement observations together with their collection time;
- source-native captions/transcripts if the source provides them;
- media URLs plus local/object-store references and checksums when downloaded.

Transcription, OCR, vision interpretation and other derived multimodal processing belong to Data Analysis preprocessing, not Collection.

## Privacy boundary

Plugin code and synthetic/public example configuration may be public. Credentials, browser state, private targets, operational endpoints, protected datasets and private study configuration must remain under ignored `data/`, environment variables or external private infrastructure.

`CollectionContext.privacy` is copied into collection provenance metadata on every plugin-produced record. Downstream modules can therefore carry the project's privacy/access policy alongside the source record without Collection changing the canonical schema.

## Telegram Phase 1 policy

The Telegram plugin uses Telethon behind the common plugin seam. Public channels use stable `https://t.me/<channel>/<message_id>` identity; non-web/private targets use the stable `telegram:<channel>:<message_id>` URI form. The message ID is also retained as a source-native identifier.

Pagination uses a numeric Telethon `max_id` cursor and returns the final message ID in the page as `next_cursor`. Shared `CollectionRunner` deduplication therefore remains based on canonical `source_url`, while cursor state is orchestration metadata rather than identity.

The raw-source policy is lossless-at-source: preserve `Message.to_dict()` inline when available and optionally attach an immutable `raw_ref` prefix supplied by private runtime configuration. Media is represented as a source reference for the later media/download stage; OCR, ASR, framing and interpretation remain Analysis responsibilities.

Telethon `FloodWait`/timeout/server/transport failures are surfaced as retryable errors. Flood-wait seconds become retry metadata, but the shared retry policy caps the actual delay and attempt count. Deterministic configuration/session failures are terminal.

API ID/hash, session paths or strings, phone/login material and real channel target lists are runtime-private and must never be committed. CI and public tests use synthetic fixtures and injected clients only. Any authenticated live smoke test is an external deployment check.

## Data Analysis handoff

Data Analysis consumes canonical records, not source-specific collector classes. The existing `build_handoff()` contract derives a stable handoff key and routing information from those records. Source plugins therefore remain invisible to Analysis except through normal provenance.

This is the core design rule:

> Collect from anything, persist one canonical source-identified record, then hand the same contract to Data Analysis.
