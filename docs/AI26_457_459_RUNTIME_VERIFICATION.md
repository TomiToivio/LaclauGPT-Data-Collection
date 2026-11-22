# AI26 runtime verification: Collection #457 and #459

PR #464 (commit `57649c7`) delivered the repository-side fixes. **A GitHub
merge is not a Laskin deployment.** This is a checklist for the Laskin operator.
Never paste private source manifests, URLs, credentials or sampled records into
public issues.

## Deployment gate

1. Coordinate with the hourly Laskin collector at :10. Do not move the checkout
   while a collection cycle or other writer is running. Preserve uncommitted work.
2. From `/mnt/workspace/LaclauGPT-Data-Collection`, inspect:
   ```bash
   pwd
   git status --short
   git fetch origin main
   git rev-parse HEAD
   git rev-parse origin/main
   ./.venv/bin/python -c 'import laclaugpt_data_collection; print(laclaugpt_data_collection.__file__)'
   ```
   If dirty or the import points outside the checkout, investigate first; do
   not use a hard reset.
3. Run read-only preflight:
   ```bash
   ./.venv/bin/python scripts/check_ai26_runtime.py --root "$PWD" --checkout "$PWD" --fetch --json
   ./.venv/bin/python scripts/deploy_ai26_sources.py
   ./.venv/bin/python scripts/deploy_ai26_study_config.py
   ```
   **Do not** automatically apply changes to either private config. Source
   coverage drift represents a sampling-frame decision, not a schema risk.
4. After approval and coordination, fast-forward the code only:
   ```bash
   git merge --ff-only origin/main
   ```
   Run the package import and the read-only checker again. Apply any
   approved private config changes using the documented deploy tools only
   after reviewing their dry-run diffs. Keep their removal safeguards.
5. Allow one fresh :10 cycle; don't manually run a concurrent second writer.

## #457: inspect runtime verdict

The cycle **JSON summary** (not merely its startup preamble) must contain
`runtime_drift.status` and `runtime_drift.findings`. Valid status values:

- `in_sync`: no drift
- `stale_compatible`: configured coverage or behind-HEAD changes that did
  not touch the guarded canonical/models/schema paths; collection may proceed
- `blocked`: schema-affecting upstream changes, an unverifiable code state,
  or another blocking runtime check; collection must refuse to run

Confirm a safe synthetic Git-repository test of both a non-schema upstream
edit and a `src/laclaugpt_data_collection/models.py` edit. **Do not simulate
schema drift by modifying the live Laskin checkout.** A blocked preflight is
not itself a completed collection cycle; no `records_new` should be claimed.

## #459: inspect language provenance

In the new cycle summary verify `language_undetermined_stored` is present and
numeric, alongside `records_synced`, `records_new`, and `warnings`.
Check a small, authorized, read-only sample of newly stored canonical records
from Bluesky, Mastodon and RSS. The source metadata should include:

- `source.raw_metadata.language_status`: `determined` or `undetermined`
- `source.raw_metadata.language_reason`: e.g. `source_metadata`,
  `detected_langdetect`, `insufficient_text`, `low_confidence`
- `source.raw_metadata.language_provenance`: e.g. `platform_or_feed_metadata`,
  `manifest_row`, `detector`, or `abstained`

A short message without a platform language must remain unlabelled
(`undetermined` with `insufficient_text`), not be assigned a guessed
language. A valid Mastodon `status.language` must take precedence over
detection. Never infer language from an account's identity or name.
Check counts for **successfully stored** records rather than the number
seen/fetched. Existing pre-deployment records are not automatically backfilled.

## Evidence to record on each issue

Record (without private content): deployed Git commit, import path relative
to checkout, cycle timestamp (local timezone), `runtime_drift.status`,
`language_undetermined_stored`, `records_synced`, and any sanitized
errors. Close the issues only after the appropriate runtime acceptance
criteria are observed; a passing CI run alone is not enough.

If a new cycle fails, keep issues open, save its sanitized diagnostics, and
follow the existing `AI26_LASKIN_RUNTIME_RELEASE_GATE.md` rollback procedure.
