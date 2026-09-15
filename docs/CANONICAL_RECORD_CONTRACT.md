# Canonical source-record contract

Collection emits stable, JSON-compatible source records. `source_url` is normalized and is the identity anchor whenever a source exposes a stable URI; platform-native identifiers remain aliases. A missing web URL receives the deterministic fallback `urn:laclaugpt:<platform>:<document_id>` at the identity boundary, never a storage-row identifier.

Backends may add internal keys, but CSV, JSONL, SQLite, MongoDB-like documents and downstream modules retain the canonical source identity, schema version, nested media references, timestamps and provenance unchanged. Collection owns source provenance and media references; analysis-derived OCR, transcript interpretation and discourse codes belong downstream.
