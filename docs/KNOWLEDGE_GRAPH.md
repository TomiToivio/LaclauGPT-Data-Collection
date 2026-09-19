# Collection RDF / knowledge-graph boundary

Issue #117 adds an optional projection layer after the canonical collection record.
Existing collectors, browser flows and storage commands remain unchanged when KG
support is disabled.

## Stable identity policy

Semantic identity must never use MongoDB ObjectIds, CSV row numbers or filesystem
positions. The canonical source identity remains CanonicalRecord.source_url. Other
graph objects use stable_uri(kind, identity), a deterministic URI derived from a
stable natural identity.

| Object | Stable identity input |
| --- | --- |
| study / collection | configured study ID |
| document / post / article / transcript | canonical source_url |
| platform / channel | normalized platform/channel identifier |
| author/account/person/organization | platform plus source author/account ID |
| media asset | durable object ref, source URL, or collector media ref |
| raw/downloaded object | durable raw/object ref |
| collection activity | provenance ID, or deterministic provenance tuple |
| research note | its own canonical note URI when represented as a collected source |

Generated LaclauGPT URI hashes are encoding details, never backend identities.

## Vocabulary mapping

Collection uses existing terms whenever practical:

- Schema.org for documents, projects, people/accounts, platforms, media, authorship
  and containment.
- DCTERMS for source and identifier metadata.
- PROV-O for collection activities, software agents, derivation and inputs.
- Web Annotation is reserved for later source-span selectors.
- https://laclaugpt.org/ns/ is used only when established vocabularies do not fit.

The JSON-LD context lives at schemas/collection-context.jsonld. Representative
Phase-0 SHACL shapes live at schemas/collection-shapes.ttl.

## Canonical projection

Collectors do not write graph-database structures. They keep producing
CanonicalRecord. Call project_record(record, study_id=...) at an explicit export or
persistence boundary to obtain KGNode and KGEdge objects.

The projection records original URL/platform, collection timestamps,
collector/tool/version, study membership, raw-vs-normalized derivation, media,
parent/reply relations when available, and collection provenance.

## Backends

The same projection can be represented without changing semantic identity:

- Local / CSC: write_csv_tables(), SQLiteKGStore, JSON-LD and RDF serializations.
- MongoDB: to_mongo_graph_documents() produces entity and relation documents with
  semantic_id fields. Mongo _id is never semantic identity.
- ArangoDB: to_arango_documents() produces vertices and edges with backend _key
  values plus the unchanged semantic_id. No Arango schema leaks into collectors.

RDFLib and PySHACL are optional. Install the kg extra for Turtle, JSON-LD/N-Quads
and SHACL validation. Merely importing or running collection code does not require
them.

## Phase activation

Phase 0 provides design, stable identifiers, export/projection, fixtures and
validation. Phase 1 analysis can refer to collection objects by semantic_id and add
source-span/media links. DNA/SNA-specific semantics stay out of Collection; the
stable actor/source/media identities created here are enough for later Phase-2
relationships.

## Existing-data migration and re-export

No migration is required. Read old data through the existing bounded canonical
migration/interchange adapter and then project the resulting CanonicalRecord.
Because semantic IDs derive from canonical source identity and durable source refs,
re-exporting the same logical record produces the same IDs across local, MongoDB
and ArangoDB representations.
