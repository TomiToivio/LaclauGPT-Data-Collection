# Optional graph/vector RAG indexing

Data Collection remains authoritative for acquisition, normalization, provenance, and canonical storage. Graph/vector indexing is an optional post-save side effect. A Neo4j, vector database, embedding service, or Ollama outage must never prevent a canonical record from being stored.

## Contract

The canonical record identity is `source_url`. Downstream indexers receive a graph-ready payload containing the canonical ID, dataset, platform, source type, language, collection timestamps, collector/version, raw-source reference/checksum, raw metadata, normalized content, and collection provenance.

Collection may create only source-factual relations that are directly supported by collected metadata, currently including `FROM_SOURCE`, `ON_PLATFORM`, `IN_DATASET`, and `HAS_LANGUAGE`. Theoretical relations such as `ARTICULATED_WITH`, ideological formation, antagonism, or empty-signifier status belong to Data Analysis.

Call the hook only after authoritative storage succeeds:

```python
storage.save(record)
result = index_after_save(
    record,
    enabled=settings.rag_enabled,
    indexer=indexer,
    dataset=settings.rag_dataset,
    failure_log=settings.rag_failure_log,
)
```

Repeated calls use a stable idempotency key derived from canonical `source_url` plus dataset. The bundled Neo4j adapter uses `MERGE`, so retries do not create duplicate canonical record/platform/dataset/language/source nodes.

## Local laptop profile

RAG is disabled by default. For a local Neo4j instance, install the optional extra and configure runtime-only values in `.env`:

```text
pip install -e '.[rag]'
LACLAUGPT_RAG_ENABLED=true
LACLAUGPT_RAG_BACKEND=neo4j
LACLAUGPT_RAG_DATASET=AI26
LACLAUGPT_NEO4J_URI=neo4j://127.0.0.1:7687
LACLAUGPT_NEO4J_USER=neo4j
LACLAUGPT_NEO4J_PASSWORD=<local secret>
```

Ollama is not required. If a future collection-side helper needs embeddings, it must use the shared configurable capability-aware model policy rather than hard-coding a chat model. `embedding_provider`, `embedding_endpoint`, and `embedding_model` are therefore configuration-only extension points.

## Linux server / distributed profile

Collectors can write canonical records locally or to shared MongoDB/S3 while indexing into a local or remote Neo4j service. Use the same settings with a remote `LACLAUGPT_NEO4J_URI`. Do not commit private endpoints, usernames, passwords, tokens, or research-specific infrastructure details.

A distributed deployment may instead provide another object implementing the `RecordIndexer` protocol, for example a Redis/task-queue publisher. This keeps collection machines decoupled from the semantic index service.

## Failure and replay

`index_after_save()` catches indexer failures and returns status `failed`; it does not re-raise. If configured, it appends a small JSONL replay hint under the private `data/` tree. Canonical storage remains the source of truth, so the semantic graph can always be rebuilt by iterating stored canonical records and calling the same idempotent indexing hook again.

The failure log is diagnostic only. It must not contain credentials or replace canonical storage.
