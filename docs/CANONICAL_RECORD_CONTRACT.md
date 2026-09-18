# Canonical source-record contract

Collection emits stable, JSON-compatible source records. `source_url` is normalized and is the identity anchor whenever a source exposes a stable URI; platform-native identifiers remain aliases. A missing web URL receives the deterministic fallback `urn:laclaugpt:<platform>:<document_id>` at the identity boundary, never a storage-row identifier.

Backends may add internal keys, but CSV, JSONL, SQLite, MongoDB-like documents and downstream modules retain the canonical source identity, schema version, nested media references, timestamps and provenance unchanged. Collection owns source provenance and media references; analysis-derived OCR, transcript interpretation and discourse codes belong downstream.


## Collection → Analysis Phase 1 contract

Collection and Analysis define **separate** Pydantic models with the same name
(`CanonicalRecord`), because each module owns different layers of the research
record:

- Collection owns the collected source: identity, native IDs, timestamps,
  language, raw preservation, media/frame references and source provenance.
- Analysis owns the same sections **plus** the research layers: `intermediate`,
  `evidence`, `analysis`, `human_readable`, `review` and `legacy`.

The bridge is `laclaugpt_data_analysis.interchange.from_collection_record`, which
converts a Collection record into the Analysis canonical record.

### Versions

| Version | Meaning |
| --- | --- |
| `schema_version` `1.1.0-draft` | the canonical record shape shared by the fixture below |
| `handoff.contract_version` `1.0` | the delivery envelope produced by `build_handoff` |

The record and its delivery envelope are versioned independently. `handoff` is
**transport metadata** — it routes a record (status, revision, arena, run ID) and
is not a field of the canonical record itself. Adapters must not treat it as
record content, and must not silently discard it.

### Compatibility fixture

`tests/fixtures/ai26_collection_handoff_v1.json` is the authoritative synthetic
AI26 handoff record. It is **vendored in both repositories** so each module can
assert the same contract in its own CI:

- `tests/test_issue_75_handoff_contract.py` (this repository) validates the record
  Collection emits, and that it stays analysis-neutral.
- `tests/test_issue_75_collection_handoff_contract.py` (Data Analysis) converts the
  same bytes through the real adapter and asserts nothing is lost.

### What must survive the boundary

A conversion may not lose, and must round-trip, at least:

- canonical `source_url` (the identity anchor)
- `source_native_ids`
- timestamps (`created_at`, `collected_at`)
- language and source metadata (`platform`, `author`)
- media references, including `kind`, `media_type`, `ref`, `media_index`,
  `object_ref` and `checksum`
- frame references (`media_ref`, timestamp)
- provenance (`provenance_id`, `method`, `model_version`)

Both models forbid unknown fields (`extra="forbid"`), so a shape mismatch fails
loudly at validation rather than dropping data quietly. Field-name drift is
therefore a breaking change, not a cosmetic one: adding a field on one side
without the other turns conversion into a `ValidationError`.

### Keeping the fixture authoritative

Fixture drift is a contract defect. When either model changes, update the fixture
in **both** repositories in the same change, so the two CI suites keep agreeing
about the same bytes.
