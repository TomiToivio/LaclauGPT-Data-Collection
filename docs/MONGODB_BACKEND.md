# MongoDB + CSV storage contract

LaclauGPT Data Collection treats MongoDB as an optional shared remote document store that can also carry lightweight graph relationships and vector-ready enrichment. CSV remains the dependency-free portable minimum.

## Backend modes

Set `LACLAUGPT_RECORD_BACKEND` to one of:

- `auto` (default): use MongoDB only when `LACLAUGPT_MONGODB_URI` is explicitly configured and reachable; otherwise use CSV.
- `mongodb`: require the configured MongoDB and fail clearly when it is unavailable.
- `csv`: use only `LACLAUGPT_CSV_PATH` and the local filesystem. MongoDB is never contacted.
- `sqlite`: retained for backwards compatibility with existing local deployments.

`auto` deliberately does **not** invent a localhost or cloud MongoDB endpoint. An empty MongoDB URI means local-only operation.

### Laptop / zero infrastructure

```bash
export LACLAUGPT_RECORD_BACKEND=csv
export LACLAUGPT_CSV_PATH=./data/csv/records.csv
laclaugpt-collect ...
```

Data path:

```text
collector -> canonical record -> CSV -> local filesystem
```

### Remote/shared MongoDB

```bash
export LACLAUGPT_RECORD_BACKEND=mongodb
export LACLAUGPT_MONGODB_URI='mongodb://USER:PASSWORD@HOST:27017/?tls=true'
export LACLAUGPT_MONGODB_DATABASE=laclaugpt
# optional; otherwise project-scoped collection naming is used
export LACLAUGPT_MONGODB_COLLECTION=documents
```

Never commit the URI, credentials, private host names, `.env`, or research data.

### Graceful degraded mode

```bash
export LACLAUGPT_RECORD_BACKEND=auto
export LACLAUGPT_MONGODB_URI='mongodb://configured-private-host:27017'
```

If the configured server cannot be reached during store construction, Data Collection logs the failure and writes canonical records to CSV instead. Explicit `mongodb` mode never falls back silently.

## Canonical graph and vector representation

Collection keeps the common record storage-neutral. Until the cross-module canonical schema promotes dedicated fields, optional downstream enrichments use the existing `analysis` namespace:

```json
{
  "source_url": "https://example.org/post/1",
  "analysis": {
    "relationships": {
      "targets": ["https://example.org/post/2"],
      "reply_to": ["https://example.org/post/0"],
      "actors": ["actor:example"],
      "organizations": ["org:example"],
      "events": ["event:example"],
      "locations": ["location:example"]
    },
    "embeddings": [
      {
        "vector": [0.1, 0.2, 0.3],
        "model": "example-embedding-model",
        "version": "1"
      }
    ]
  }
}
```

Data Collection does not need to generate embeddings. It must preserve any graph references and vectors already present. CSV serializes the entire nested `analysis` object as deterministic JSON, so CSV -> MongoDB transfer is lossless at the canonical-record level.

## MongoDB graph traversal

`MongoRecordStore.graph_lookup()` provides a bounded `$graphLookup` over URI references. The default relationship path is `analysis.relationships.targets` and the configured `LACLAUGPT_MONGODB_GRAPH_MAX_DEPTH` caps recursion.

Conceptually the generated aggregation is:

```javascript
{
  $graphLookup: {
    from: "<records collection>",
    startWith: "$analysis.relationships.targets",
    connectFromField: "analysis.relationships.targets",
    connectToField: "source_url",
    as: "related_records",
    maxDepth: 3,
    depthField: "graph_depth",
    restrictSearchWithMatch: { project_id: "AI26" }
  }
}
```

This intentionally supports lightweight knowledge/relationship traversal without introducing Neo4j, ArangoDB or another mandatory graph service.

## Vector capability

`MongoRecordStore.capabilities()` reports backend capabilities conservatively. MongoDB presence alone is not treated as proof that native vector search is enabled: deployment type, server features and a suitable vector index must all be checked by the downstream module that wants to execute vector search.

Data Collection therefore guarantees only that vector payloads and their model/version metadata survive persistence. Native vector search is an optional enhancement, never a startup requirement.

## Security

Use authenticated MongoDB with TLS for remote deployments. Do not expose an unauthenticated MongoDB listener publicly. Keep real URIs and credentials in environment variables or private configuration outside Git. Public examples and tests use synthetic data only.
