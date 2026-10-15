# Refreshing the AI26 runtime on Laskin

The runtime on this host and the repository drift apart. It has happened three
times: **#206** ("deployed collection config is stale and hand-edited"), **#246**
(the running collector still polling a dormant target after the audited fix had
merged), and **#270** (the audited source manifest 10 hours behind, `in_sync:
false` in every cycle). Each was repaired by hand; none of the repairs stuck,
because until #277 there was **no step that moves the runtime from the repository
to the host** and no check that says loudly when it has not happened.

This document is that procedure. It is deliberately manual.

## Why this is not automated

Deploying content **changes what the hourly production pipeline samples**. Dropping
a source identity or switching an audited replacement on is a sampling decision,
and the `--allow-removals` guard on the deploy tool exists precisely so that it
cannot happen silently. An automation may therefore **detect and report** a stale
runtime; it must never refresh one.

The second symptom this addresses is quieter: the code checkout. When a merged fix
sits one commit behind `origin/main`, the fix is merged and inert, and nothing
anywhere says so.

## Step 0 — ask whether anything is stale

Read-only, no side effects, safe to run at any time:

```bash
cd /mnt/workspace/LaclauGPT-Data-Collection
.venv/bin/python scripts/check_ai26_runtime_freshness.py
```

It reports three independent facts and one verdict:

| Exit | Verdict | Meaning |
| --- | --- | --- |
| 0 | `RUNTIME FRESH` | deployed configs and the checkout both match the repository |
| 1 | `RUNTIME STALE` | at least one of them disagrees — nothing has been changed for you |
| 2 | `RUNTIME UNKNOWN` | a check could not be completed. **This is not an all-clear**; fix the check first |

`--json` gives the same report machine-readably, and `--quiet` prints only the
verdict line, for a log or a report. The source-manifest comparison is the
identity-aware one the hourly collector itself uses, so a row retired by a
decision (retained with `enabled = false` and an `inactive_reason`) does **not**
count as drift. If the package cannot be imported the script says so and falls
back to a byte comparison — labelled as the weaker check it is, never as the real
one.

## Step 1 — refresh the private config copies

Both tools are **dry-run by default**, print the exact diff, and back up before
writing. Review the diff before applying: it is the sampling frame.

```bash
.venv/bin/python scripts/deploy_ai26_sources.py        # dry run: what would change
.venv/bin/python scripts/deploy_ai26_study_config.py   # dry run

.venv/bin/python scripts/deploy_ai26_sources.py --apply --allow-removals
.venv/bin/python scripts/deploy_ai26_study_config.py --apply
```

`--allow-removals` is required when the deploy retires an active identity. That
flag is the sampling guard, not an inconvenience: read the removals it prints and
satisfy yourself that each one is the audited decision.

Both writes go through a temporary file and an atomic rename, so the collector can
never read a half-written manifest even if a cycle starts mid-deploy.

## Step 2 — refresh the code checkout

The wrappers in `scripts/` run from this checkout, so a stale checkout means the
collector is running old code. Never `reset --hard` a working tree that has
changes; check first.

```bash
git -C /mnt/workspace/LaclauGPT-Data-Collection status --porcelain   # must be empty
git -C /mnt/workspace/LaclauGPT-Data-Collection pull --ff-only origin main
```

A shared checkout may have moved under you — check the branch before and after:

```bash
git -C /mnt/workspace/LaclauGPT-Data-Collection rev-parse --abbrev-ref HEAD
```

## Step 3 — confirm, then watch one cycle

```bash
.venv/bin/python scripts/check_ai26_runtime_freshness.py     # expect RUNTIME FRESH
```

Then let one `collect` cycle run (hourly, at `:10`) and read its `manifest_drift`
block from `data/logs/ai26-laskin-collect.log`: it should read `in_sync: true`
with `deployed_total == tracked_total`. The cycle log is the independent
confirmation — the same comparison running inside production, rather than the
check's word for it.

## Rollback

Every deploy writes a timestamped backup beside the file it replaced:

```bash
ls -la /mnt/workspace/LaclauGPT-Data-Collection/data/config/*.backup-*
# restore exactly, then re-run the check
cp data/config/ai26.sources.toml.backup-<stamp> data/config/ai26.sources.toml
```

For the code checkout, `git switch` / `git reset --hard <sha>` back to the previous
commit — this is the one step where the working tree must be clean first.

## Not covered here

- **Enabling, disabling or changing cron.** The installer scripts own that, and
  no step in this procedure activates anything.
- **Any write to a database, bucket or store.** This procedure moves files and a
  checkout, nothing else.
- **Automating the refresh.** See "Why this is not automated" above. If a report
  line is wanted in the daily technical job, that is a separate, deliberate change
  to that job — detection only.
