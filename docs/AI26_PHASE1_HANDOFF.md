# AI26 Phase 1 Collection -> Analysis handoff contract

This document pins the authoritative Collection-to-Analysis boundary for the AI26 Phase 1 pipeline.

## Authoritative contract

- **Contract version:** `ai26-phase1-handoff-v1`
- **Canonical schema version:** `1.1.0`
- **Producer:** `LaclauGPT-Data-Collection`
- **Consumer:** `LaclauGPT-Data-Analysis`
- **Authoritative model:** `laclaugpt_data_collection.models.CanonicalRecord`
- **Compatibility constructor:** `NormalizedRecord` for legacy collectors only. It is an adapter into `CanonicalRecord`, not a second handoff schema.

Collection hands the same nested canonical record to Analysis. There is no separate flat AI26 transport model. The contract is intentionally analysis-neutral: Collection may populate source identity, source metadata, content, raw capture, intermediate source-derived material, media/frame references and collection provenance, but it must not fabricate Laclaudian or other analytical results.

## Required invariants

The handoff must preserve:

1. `source_url` as semantic identity;
2. every `source_native_ids` alias;
3. source creation and collection timestamps;
4. normalized text and source/content language;
5. media references and frame references as references, not embedded research media;
6. collection provenance and raw-capture references.

Analysis may enrich the record additively after this boundary. It must not require Collection to emit analytical fields.

## Compatibility fixture

The synthetic fixture at `tests/fixtures/ai26_phase1_handoff_v1.json` is the CI-consumable boundary sample. It contains only synthetic data and is safe to vendor in Data Analysis as the same contract fixture.

Run:

```bash
python tools/verify_contracts.py
```

The conformance tool validates both the general canonical parity fixture and this AI26 handoff fixture.
