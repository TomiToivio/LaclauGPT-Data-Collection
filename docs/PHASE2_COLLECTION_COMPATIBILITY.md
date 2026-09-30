# Phase 2 Collection compatibility review

Issue: #195

Phase 2 adds Discourse Network Analysis (DNA), Social Network Analysis (SNA), and RDF work downstream. Collection remains responsible only for source acquisition, stable identity, raw preservation, source metadata, media references, and collection provenance.

## Result

The current Collection contract is sufficient for Phase 2. No new DNA/SNA/RDF analysis logic belongs in this repository, and no canonical-schema change is required for the Phase 2 start.

The important invariant is that Collection preserves source-native facts so Analysis can later construct analytical statements, observed interaction edges, inferred relations, and RDF resources without pretending that downstream inference came from the collector.

## Phase 2 requirements

| Requirement | Current support | Notes |
| --- | --- | --- |
| Stable source/document identity | Yes | `source_url` is the canonical semantic identity; URI-like fallbacks are deterministic. |
| Source-native document IDs | Yes | Preserved in `source_native_ids`. |
| Author/actor identity | Yes | Human-readable author fields live in `source`; source-native actor IDs can be retained in `source_native_ids` and/or raw source metadata. |
| Source-created timestamp | Yes | `source.created_at`. |
| Collection timestamp | Yes | `source.collected_at`, `raw_capture.captured_at`, and provenance capture time are available. |
| Platform/source type | Yes | `source.platform` and `source.source_type`. |
| Reply/repost/quote relationships | Yes, when exposed by the source/adapter | Retained losslessly in `raw_capture`; existing compatibility adapters also promote known IDs into `source.raw_metadata["interaction_ids"]`. |
| Mentions/referenced actors | Yes, when exposed | Retained in raw capture; existing adapters preserve mentions and related source metadata. |
| Thread/conversation IDs | Yes, when exposed | Raw capture preserves them; the legacy X/Twitter adapter promotes `conversation_id` into `interaction_ids`. |
| Referenced documents | Yes, when exposed | Parent/repost/quote IDs are retained as source-native metadata rather than converted into analytical edges. |
| Raw collector payload | Yes | `raw_capture.payload` or immutable `raw_capture.ref`; collectors are expected to preserve at least one. |
| Media references | Yes | Canonical `content.media_references` and file references, including durable object refs/checksums where available. |
| Collection provenance | Yes | Versioned `CollectionProvenance` with collector/module/run/method/input/transform metadata. |
| Observed vs inferred relation | Yes | Collection stores source-native facts only; DNA statements, SNA edges, communities, centrality, and theory-derived relations remain downstream. |

## Interaction metadata policy

Collection intentionally does **not** define DNA statements or SNA edges.

Source-native interaction information may appear in two places:

1. the lossless `raw_capture`, which is authoritative for source-specific fields; and
2. adapter convenience metadata such as `source.raw_metadata["interaction_ids"]`.

For example, the existing legacy X/Twitter adapter preserves source-provided parent/reply, repost, quote, conversation, and referenced-actor identifiers. These are observed source fields, not analytical graph edges.

Not every collector promotes every platform-specific interaction field into the same convenience dictionary. That is not a Phase 2 blocker because the raw payload is retained. A future cross-platform interaction-normalization vocabulary should only be introduced together with the Analysis contract, a schema-version decision, fixtures, and migration tests. It should not be improvised in Collection for Phase 2.

## DATS interoperability

The current interoperability layer already treats DATS as a document/source interchange partner rather than a second collector or analytical schema.

Collection preserves:

- DATS document/project identifiers;
- source URL and source metadata;
- text/title/language;
- file and media references;
- the complete imported DATS document in raw capture.

DATS annotations, codes, classifications, corrections, and analytical relations remain in Analysis/Visualization. No DATS collector duplication is needed.

## RDF readiness

Current identities are sufficient for downstream RDF construction:

- canonical source identity: `source_url`;
- platform/source aliases: `source_native_ids`;
- raw provenance: `raw_capture` + `provenance`;
- durable media/object identity: media refs, checksums, and object refs.

RDF URI minting, triples, ontologies, provenance graphs, and analytical relations belong in Analysis. Collection should not emit theory-laden RDF assertions.

## Non-blocking caveat

The canonical record does not currently expose a single strongly typed cross-platform interaction object. Platform adapters may promote source-native interaction fields differently.

For Phase 2 this is acceptable because:

- raw payload preservation prevents information loss;
- existing social-data compatibility code already retains common reply/repost/quote/conversation fields;
- adding a canonical interaction model now would require synchronized Collection/Analysis schema and fixture changes;
- Phase 2 can begin by deriving observed interaction records in Analysis from preserved source-native metadata.

If repeated Phase 2 implementation work shows that multiple collectors need the same source-native interaction projection, add it later as a small, versioned, backward-compatible cross-repository contract change.

## Decision

No collector redesign or new Collection analysis code is required for Phase 2.

Collection remains an acquisition/provenance layer. DNA, SNA, RDF construction, graph metrics, communities, centrality, Castells/Esposito concepts, and inferred relationships stay downstream.
