# Legacy flat-Mongo adapter retirement plan

> **Terminology.** The file name, module name and `phase-0` branch keep the historical
> Phase 0 label for traceability. Phase 0/Phase 1 here name the paper-era code lineage and
> its compatibility boundary, not software stages that this repository passes through.

Issue: #112  
Status: planning/gate only  
Runtime effect: none

## Purpose

This document defines the conditions and rollback procedure for eventually retiring the
legacy flat-MongoDB compatibility boundary:

- `src/laclaugpt_data_collection/phase0_mongo.py`
- `laclaugpt2_<project>_scraper_collection`
- the flat Collection -> Data Analysis handoff from the paper-era Phase 0 work

This issue does **not** authorize deletion, renaming, collection migration, or a runtime
switch. The legacy path remains a preserved compatibility path until every gate below is met.

## Current boundary

The legacy path writes flat MongoDB documents to:

```text
laclaugpt2_<project>_scraper_collection
```

The current pipeline writes nested canonical records through the canonical storage
contract, normally to:

```text
<project>__records
```

The retirement target is complete end-to-end use of the canonical record by Collection
and Data Analysis, without an implicit translation dependency on the flat legacy schema.

## Preconditions

Retirement work must not begin until all of the following are true.

### 1. Collection contract parity

- Required source/plugin contracts are green.
- Canonical identity and deduplication behavior are covered by tests.
- Storage tests are green for the backend(s) used in production.
- Source-specific adapters needed by the active study are green.
- Browser/platform collectors preserve provenance, privacy and source identity.
- No active Collection code path requires `phase0_mongo.py` for successful canonical
  persistence.

### 2. Data Analysis contract parity

- Data Analysis reads the canonical record directly.
- Analysis no longer requires the flat `source_*` field layout as its primary input
  contract.
- Analysis integration tests consume representative canonical records produced by
  Collection fixtures.
- Analysis preserves source identity, provenance, timestamps, text/media references and
  project metadata without a lossy flattening step.
- Reprocessing/idempotency behavior is proven against canonical records.

### 3. End-to-end parity

At least one representative record for every source family used in production must pass:

```text
source
  -> collector/parser
  -> CanonicalRecord
  -> durable canonical storage
  -> Data Analysis ingestion
  -> analysis persistence/output
```

The test must verify:

- stable identity survives the handoff;
- the same item is not analyzed twice after recollection;
- required text and metadata survive intact;
- media references survive for multimodal records;
- provenance remains traceable;
- malformed/partial records fail explicitly rather than being silently flattened.

### 4. Production smoke evidence

Before retirement, capture a bounded production smoke run with:

- project/study identifier;
- source adapters exercised;
- record counts collected, inserted, updated and skipped;
- Analysis ingestion counts;
- dedup/idempotency result from a repeated run;
- error count and representative error classes;
- proof that no legacy flat-record collection is required for a successful canonical
  run.

Do not commit private source data, credentials, target lists or raw participant content.
Store only sanitized evidence or aggregate counts in the public repository.

## Migration procedure

The eventual retirement should be a separate implementation issue/PR and use this order.

1. Freeze the known-good legacy baseline branch/tag and record the exact commit.
2. Run the full Collection test suite and public-tree/privacy checks.
3. Run the required Data Analysis integration suite against canonical fixtures.
4. Run a bounded production smoke collection into the canonical collection.
5. Run Data Analysis against only the canonical collection and record parity evidence.
6. Repeat the same collection window to prove idempotency/deduplication.
7. Verify dashboards/consumers use Analysis output rather than reading the legacy flat
   collection directly.
8. Disable the legacy adapter only behind an explicit configuration/runtime change.
9. Keep the flat collection untouched for the rollback window.
10. After a defined observation period with no rollback trigger, remove obsolete legacy
    runtime references in a separate cleanup PR.
11. Delete or archive old flat data only through an explicit operational decision,
    never as part of code deployment.

## Rollback plan

Rollback must be possible without reconstructing lost source data.

### Rollback assets that must exist before migration

- preserved `phase-0` branch;
- last known-good legacy commit SHA;
- `phase0_mongo.py` still present until the cleanup stage;
- flat legacy Mongo collection retained unchanged;
- prior deployment configuration retained;
- commands/runbook for restoring the legacy RSS -> flat Mongo -> Analysis path.

### Rollback triggers

Rollback immediately if any of these occur after switching:

- Analysis cannot ingest a required source family;
- source identity changes or duplicate analysis appears;
- canonical fields needed by Analysis are missing or lossy;
- provenance/media references are dropped;
- record counts diverge materially without an explained source-side reason;
- production errors exceed the accepted smoke baseline;
- a required consumer still depends on the flat collection.

### Rollback steps

1. Stop the canonical writer/Analysis run that is producing bad output.
2. Restore the last known-good runtime configuration.
3. Re-enable the legacy Collection and flat Analysis handoff.
4. Point Analysis back to `laclaugpt2_<project>_scraper_collection`.
5. Verify one bounded legacy collection + analysis cycle.
6. Preserve the failed canonical records for diagnosis; do not silently overwrite them.
7. Open a regression issue with sanitized evidence before attempting the migration again.

## Data migration policy

Retiring the adapter does not require destructive migration of historical legacy data.

Preferred order:

1. New records move to the canonical path.
2. Historical flat legacy records remain readable for reproducibility.
3. If historical backfill is required, use an explicit, versioned migration tool with
   dry-run output and deterministic identity mapping.
4. Never rewrite historical records in place without a backup and a separately reviewed
   migration issue.

## Evidence checklist for the retirement PR

The future retirement PR must include links or artifacts for:

- [ ] Collection unit/integration suite green.
- [ ] Data Analysis canonical-ingestion suite green.
- [ ] Collection -> Analysis end-to-end fixture test green.
- [ ] Repeated-run dedup/idempotency test green.
- [ ] Privacy/public-tree checks green.
- [ ] Production smoke evidence recorded.
- [ ] Last known-good legacy commit recorded.
- [ ] Runtime/config rollback instructions verified.
- [ ] No remaining production consumer of the flat collection.
- [ ] Explicit approval to perform the runtime switch.

## Non-goals for issue #112

Issue #112 must not:

- delete `phase0_mongo.py`;
- remove legacy-path tests;
- drop or rename the flat Mongo collection;
- change the default runtime;
- migrate production data;
- switch Data Analysis to a new collection;
- bundle cleanup with migration.

The result of #112 is this gate and rollback plan only.
