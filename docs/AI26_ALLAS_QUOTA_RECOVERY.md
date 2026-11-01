# AI26 Allas quota outage and Laskin runtime recovery (#396, #397)

This is an **operator runbook**, not proof of a live repair. GitHub changes do not update Laskin or CSC Allas. Follow [the existing Laskin release gate](AI26_LASKIN_RUNTIME_RELEASE_GATE.md) for all code and config deployments.

## Incident snapshot and scope

- First reported failed collection cycle: 2026-10-28 19:10 EET.
- 2026-11-01 16:00 EET ledger: 93 consecutive failed capture cycles, 2,790 fetched records discarded, 2,253 failed object-store writes, 0 records synced. Analysis has not completed a cycle since 2026-10-28 19:29 EET.
- Read access to bucket `LaclauGPT-AI26` works; S3 `PutObject` fails with `QuotaExceeded`. Prior measurement: 20,739 objects, 65,600,974,740 bytes (61.10 GiB). These numbers are incident evidence, **not** current measurements.
- The non-browser RSS/Bluesky collector has **no local spool** on the deployed cron sink. The merged browser capture mirror (#393) **does not** protect these records.
- #397's original nine-commit Collection drift is historical: the latest #396 ledger states Collection is now at `a4df2fa` (`origin/main`). **Independently verify** this on host. Analysis last reported at `44c79a4`, one commit behind `5f1265f`; do not assume that remains true.

## 1. Preserve evidence and diagnose safely (read-only)

On Laskin, from each deployed repository, check `pwd`, `git status --short`, `git fetch origin main`, `git rev-parse HEAD`, and `git rev-parse origin/main`. A fetch updates remote tracking refs but **does not** change the running checkout. Note the installed Python import path and whether the scheduled cron entrypoint uses that interpreter.

Run the existing runtime checker **with `--fetch`** to detect actual remote drift:

```bash
cd /mnt/workspace/LaclauGPT-Data-Collection
./.venv/bin/python scripts/check_ai26_runtime.py --fetch \
  --checkout /mnt/workspace/LaclauGPT-Data-Collection \
  --checkout /mnt/workspace/LaclauGPT-Data-Analysis \
  --checkout /mnt/workspace/LaclauGPT-Data-Visualization
```

Gather latest collector/analysis logs, elapsed failed cycles, records fetched/synced, and `QuotaExceeded` error counts. **Never print credentials, secret .env values, private source URLs, or raw research records** into GitHub comments.

Inspect storage quota/usage in CSC's authorized project interface. An S3 `head_bucket` success does not prove write access. Do not repeatedly retry uploads without capacity.

## 2. Restore capacity (requires explicit project-owner action)

**Preferred:** request/approve a quota increase for the CSC Allas project backing `LaclauGPT-AI26`. Confirm project-level quota, free space, and write authorization with CSC administrators.

**Alternative:** owner reviews a separately generated, read-only inventory and explicitly approves a retention policy and exact candidate keys **before any deletion**. Do **not** assume analysed envelopes can be safely removed: check raw-data reproducibility, research retention obligations, privacy, downstream references, and backup state. Do not run an automatic purge or delete objects based only on age or apparent analysis completion.

This runbook **does not authorize** changing project quota, deleting objects, or using other buckets/accounts to bypass limits.

## 3. Deploy merged fixes only through the release gate

A newer commit is not a quota fix. Once the operator has verified clean working trees, scheduled jobs are not actively writing, config-change dry runs are approved, and the [release gate](AI26_LASKIN_RUNTIME_RELEASE_GATE.md) is satisfied:

1. Preserve local changes and record old SHA(s). No `reset --hard`, forced update, or unattended rebase.
2. Perform required config dry runs and approved config synchronization **before** changing the code checkout.
3. For each affected checkout, perform a fast-forward-only refresh in a safe cycle window: `git fetch origin main && git merge --ff-only origin/main`.
4. Confirm the cron interpreter imports the expected repository and re-run the runtime checker with `--fetch`.
5. Verify the Analysis preflight now names `QuotaExceeded` (merged Analysis #408/#409), rather than only generic `ClientError`, if quota is still exhausted.

The Visualization checkout was reported to have a distinct local commit; **do not overwrite it** as part of this incident.

## 4. Verify actual recovery, not merely a successful deploy

After CSC confirms free quota:

- Run a bounded, safe object-store write-and-delete probe using the approved operational diagnostic; verify clean-up and record the provider error code. Avoid putting credentials in shell history or issue output.
- Observe **new** scheduled collection cycles. Require successful uploads and non-zero records synced where the current sources actually yield records; distinguish a naturally empty cycle from a failed one.
- Observe **new** analysis cycles. Require a valid preflight and successful bounded task completion while preserving stream cursors and deduplication.
- Check the next media cycle and run a read-only reconciliation for the data gap. **Do not claim lost records are recoverable** from local staging: there was none for the non-browser path.
- Report timestamp, actual host commit SHA(s), object-store probe result, collection and analysis outcomes, and remaining gaps in #396/#397. Close only after verified live recovery.

## 5. Follow-up engineering requirement: durable non-browser capture spool

A quota increase repairs the service, but cannot recover already discarded responses. Track a separate engineering implementation for RSS/Bluesky and other non-browser fetches, including:

- Write raw capture **durably and atomically to local storage before attempting S3** (with credential redaction and safe permissions). Use stable idempotency keys.
- Maintain explicit pending/uploaded states, retries with backoff, bounded local capacity, monitoring/alerts, and crash-safe replay. Do not advance source checkpoints as if records were synced when upload fails.
- Test `QuotaExceeded`, restart, partial write, duplicate replay, local disk-full, malformed records, and S3 recovery.
- Avoid claiming the browser capture mirror (#393) covers this path. Test the cron sink separately.

Do not deploy the spool until review of retention/security and bounded disk usage is complete. This documentation does **not** implement it.

## Closure criteria

- **#396:** operator-verified quota restored; latest capture and analysis cycles succeed; losses quantified and documented; local-spool gap linked to a concrete implementation issue.
- **#397:** host-verified Collection **and** Analysis revisions/current imports match reviewed deploy targets; no ongoing unapproved drift; new-cycle checks confirm deployed fixes execute. A GitHub merge alone does not satisfy this gate.
