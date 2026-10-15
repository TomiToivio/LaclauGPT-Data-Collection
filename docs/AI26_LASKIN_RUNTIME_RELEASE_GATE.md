# AI26 Laskin runtime release gate (Collection #270, #271)

This checklist is for an **operator on Laskin**, not a GitHub-only release. A merged commit does not update an installed cron job, the running Python environment, or ignored `data/config/` files. No live deployment or data migration is authorized by merely merging this document.

## 1. Establish the running revision (read-only)

From `/mnt/workspace/LaclauGPT-Data-Collection`:

```bash
pwd
git status --short
git fetch origin main
git rev-parse HEAD
git rev-parse origin/main
git log -1 --oneline
./.venv/bin/python -c 'import laclaugpt_data_collection, inspect; print(inspect.getfile(laclaugpt_data_collection))'
```

If the working tree is dirty, the installed import path points outside the expected checkout, or `HEAD` differs from the reviewed release commit, **stop and investigate** before updating. Check the Analysis checkout, worker executable and installed import path separately: matching Git commit hashes in Collection alone cannot prove the worker is updated. Preserve local operator changes; do not use `git reset --hard` as a shortcut.

## 2. Review audited configuration changes (dry-run; no data writes)

```bash
./.venv/bin/python scripts/deploy_ai26_sources.py
./.venv/bin/python scripts/deploy_ai26_study_config.py
```

For #270 the reviewed change is **71 → 66 active source identities**: seven disabled legacy feeds and two new audited Bluesky accounts, plus source arena annotations and the study configuration correction. Counts refer to the 2026-10-15 issue evidence, not a permanent expected source count. Verify exact additions/removals against the approved tracked files rather than trusting the counts alone. The removal gate is intentional. Runtime URLs and collected research records must not be copied into public issue comments.

## 3. Operator-authorized deployment only

After the responsible maintainer approves the changed sampling frame, and the checkout and cron runtime are confirmed to use the reviewed revision, apply both files:

```bash
./.venv/bin/python scripts/deploy_ai26_sources.py --apply --allow-removals
./.venv/bin/python scripts/deploy_ai26_study_config.py --apply
./.venv/bin/python scripts/deploy_ai26_sources.py
./.venv/bin/python scripts/deploy_ai26_study_config.py
```

The scripts make timestamped backups of previous runtime configuration. The last two commands must say `Already synchronized; no change.` If not, **do not close #270**. Confirm which Python revision the *scheduled entrypoint* actually imports, then inspect a new collector cycle, not an old log, for `manifest_drift.in_sync == true`. Ensure formerly disabled feeds are not polled and newly audited sources are eligible. Check P1 `tick_record_limit` independently against #273/#275; manifest synchronization alone cannot verify the worker code fix. Coordinate with cron scheduling so the verification does not overlap a writer.

## 4. Collection → Analysis schema gate (#271)

Collection canonical **persisted** records stay at `1.1.0`. Analysis canonical validation requires `1.2.0`. The `analysis_1_2_view` function is an **opt-in, non-mutating export adapter**, not a bulk database migration, and `build_handoff`'s `contract_version` is a different contract from the research record `schema_version`. Do not equate the handoff envelope with an Analysis worker manifest or stamp one field using the other.

Offline, after installing the documented dev dependencies:

```bash
./.venv/bin/python -m pytest -q tests/test_issue_271_analysis_schema_compat.py
```

Before production sign-off, use a **synthetic text-only** and a representative legacy 1.1 record to test the *actual* Analysis #341 ingestion path. Verify that its submitted worker manifest uses the version required by the deployed worker, that the exported record validates against the pinned Analysis 1.2 schema, and that identity/revision, source URL, native IDs, source provenance, raw capture, arena and `ready` behavior are preserved. Replay the same source and then change its text: expect a stable handoff key/revision on replay and a different revision on content change. Explicitly test that unknown versions are rejected, no record is rewritten in place, and no missing media is fabricated.

For a read-only live diagnosis, inspect **one actual queued handoff manifest using the operator's known queue tooling**; report its manifest `schema_version` alongside the installed Collection and Analysis constants. Do not guess a private queue key, disclose a record, or run a bulk migration. Keep #271 open until the Analysis consumer contract and read-only stored-record audit are documented in [Analysis #341](https://github.com/TomiToivio/LaclauGPT-Data-Analysis/issues/341).

## Acceptance and rollback

* **#270:** both deploy scripts report synchronized; a *new* hourly collector cycle confirms `in_sync=true`, the audited active source set and intended arena routing; installed scheduled entrypoint is the reviewed code revision.
* **#271:** both 1.1 and 1.2 fixture paths validate through the actual Analysis ingestion boundary, with deterministic replay and no destructive rewrite. Any production migration requires explicit operator sign-off.
* On a failed configuration rollout, stop the conflicting worker first, restore the timestamped runtime backups after reviewing the intended rollback, then repeat dry-run and runtime checks. Restoring manifests does **not** roll back already ingested data or installed Python code.

Until these criteria are observed on Laskin, **keep both issues open**. GitHub-only changes are not evidence that an hourly runtime was deployed.
