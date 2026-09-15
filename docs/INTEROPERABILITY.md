# LaclauGPT Interoperability Contract

`LaclauGPT-Data-Collection` is a producer module. It must not require the analysis, visualization, research-assistant or simulation packages to collect data.

## Stable record envelope

Downstream modules consume dictionaries/documents with these required fields:

- `schema_version`
- `document_id`
- `platform`
- `source_url`
- `timestamp`
- `text`
- `raw_ref`
- `collection_provenance`

Optional fields include author metadata, hashtags, mentions, engagement and media references.

Identifiers are strings. This avoids integer-range problems for platform IDs and preserves leading zeros where relevant.

## Provenance

`collection_provenance` should contain, when available:

- collector name/version;
- capture/run identifiers;
- captured-at timestamp;
- parser/module name;
- source/visited URL;
- transformation steps;
- optional Git commit/build identifier.

Raw source objects may be stored separately. `raw_ref` is the durable pointer connecting normalized records to those objects.

## Storage adapters

The public Python API exposes abstract record/object stores. Default adapters use SQLite/filesystem. Optional adapters use MongoDB/S3. Redis is coordination/cache, not the canonical record store.

Downstream modules must not depend on a specific backend. They should consume exported JSONL/CSV or the stable record envelope through a service/API.

## Module boundaries

- **Data Collection:** capture, source parsers, normalization, provenance, collection state, media/raw persistence.
- **Data Storage:** durable cross-project storage services, migrations, indexing and retention.
- **Data Analysis:** NLP/LLM/discourse analysis, codebooks and derived analytical fields.
- **Data Visualization:** dashboards, graphs and human-readable presentation.
- **Research Assistant:** agentic research workflows and tool orchestration.
- **Simulation Laboratory:** synthetic/agent simulations.

Collection may integrate with the other modules through schemas and adapters, but must not absorb their domain logic.

## Compatibility rule

Breaking changes to the normalized envelope require a schema-version bump and migration notes. New optional fields are backwards-compatible.
