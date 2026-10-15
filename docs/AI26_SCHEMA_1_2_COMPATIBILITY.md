# AI26 Collection 1.1.0 → Analysis 1.2.0 compatibility

Issues: Collection [#271](https://github.com/TomiToivio/LaclauGPT-Data-Collection/issues/271), Analysis [#341](https://github.com/TomiToivio/LaclauGPT-Data-Analysis/issues/341).

## Decision

Keep **Collection 1.1.0 as the authoritative persisted schema** for existing records. The observed Collection and Analysis JSON schemas agree on their required properties and field shapes, but constrain `schema_version` to `1.1.0` and `1.2.0`, respectively. Version equality is not evidence of a data migration. Use the explicit, opt-in `analysis_1_2_view()` adapter only at the Collection → Analysis boundary. This creates a fresh dictionary, changes its version marker and relocates Collection-only top-level extensions to `legacy._collection_compat_extensions` so strict 1.2 JSON-schema validation does not silently drop them. Records already at 1.2 can pass through the same adapter; an unknown version is refused.

**Do not run a bulk migration or overwrite MongoDB, SQLite, JSONL or Allas assets.** The adapter is for an exported handoff view and must be integrated explicitly by the Analysis consumer. Versions cannot be considered truly interoperable until the Analysis #341 worker also accepts that view.

## Handoff acceptance

The synthetic `ai26_phase1_handoff_v1.json` fixture and `test_issue_271_analysis_schema_compat.py` cover legacy 1.1 → 1.2 projection without input mutation, already-1.2 idempotency, preserved source URL/native aliases/raw capture/provenance/text, stable handoff key/revision across runs, text-only `ready`, content-triggered revision change, and fail-closed unexpected versions. Handoff metadata is kept outside the strict canonical 1.2 record as a routing envelope (or preserved in the legacy extension area if a combined document is adapted).

Run: `pytest -q tests/test_issue_271_analysis_schema_compat.py`.

## Follow-up validation before production

1. Vendor or pin the exact Analysis 1.2 JSON schema in CI and run `jsonschema.validate` on the projected fixtures, including analysis of all fields and the extension slot. An inspection of today's schemas is not a permanently pinned cross-repo contract.
2. Integrate this versioned adapter at the actual Analysis ingestion boundary and exercise Collection → Analysis on synthetic records, including replay and source-content updates.
3. Confirm operational handling of pre-existing stored 1.1 records with a read-only sample audit. Any live data migration requires operator approval.
4. Maintain the existing AI26 Phase 1 contract (`ai26-phase1-handoff-v1`) separately from the 1.2 export view; no analytical inferences are added by Collection.
