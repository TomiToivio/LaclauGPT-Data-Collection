# AC/DT backwards compatibility

This repository implements the collection side of `TomiToivio/LaclauGPT#36`.

Normative shared resources live in the core repository:

- `docs/ACDT_METHOD_CONTRACT.md`
- `schemas/acdt_method_registry.v1.yaml`
- `schemas/acdt_result.v1.schema.json`
- `fixtures/acdt/`

## Collection guarantees

The canonical collection record preserves source identity, source-native IDs, timestamps, raw capture, normalized text, language, media references and extensible source metadata. AC/DT compatibility imports additionally preserve hashtags, mentions, links, reply/repost/quote/conversation identifiers, actor IDs, collection query metadata and the complete original legacy row.

`src/laclaugpt_data_collection/acdt_compat.py` provides:

- `import_legacy_twitter()` for Twitter/X/hashtag-landscape rows;
- `import_legacy_manifesto()` for manifesto/document rows including old measurement columns;
- `export_legacy_row()` for loss-preserving round trips.

Unknown legacy fields are retained under `CanonicalRecord.legacy.original`; missing information is never fabricated. Ideological labels are never inferred during collection.

## Provenance

Compatibility imports are marked `legacy_acdt_import` and record the adapter version, study ID when supplied, transformation name and the explicit rule `missing_fields_not_inferred=true`.

Platform-specific fields that do not yet have a canonical home remain in `source.raw_metadata`, `raw_capture.payload`, or `legacy.original` rather than being discarded.

## Tests

`tests/test_acdt_compat.py` verifies Twitter/X and manifesto round trips, preservation of unknown legacy fields, interaction IDs, hashtags/mentions and legacy measurement columns.