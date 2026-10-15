# AI26 Laskin read-only refresh gate (#277)

A merged GitHub commit **does not deploy** a running collector. There are three
independent runtime copies: code checkout, private source TOML and private
study YAML. The last two are sampling decisions and remain **manual**.

## Daily human-visible check (read-only)

On the Laskin collector checkout, run:

```bash
cd /path/to/LaclauGPT-Data-Collection
git fetch origin main    # updates the local remote tracking ref; not the checkout
./.venv/bin/python scripts/check_ai26_runtime_sync.py
```

Output is **one machine-readable line** (`AI26_RUNTIME_SYNC=in_sync` or
`AI26_RUNTIME_SYNC=stale`) identifying exact truncated SHA256 hashes for
both configs and the checkout/remote revisions with ahead/behind counts.
Exit 0 only when all three copies agree and the tracked worktree is clean;
exit 1 on drift, missing files, missing remote ref, or dirty worktree.
The check itself does not fetch, deploy, pull, migrate or modify anything.
For a nightly technical report or reporting-only cron stage, invoke this
command, capture its one-line output and alert on nonzero exit. **Do not**
schedule the deploy commands. Note that a remote tracking ref is only as
recent as the operator's last fetch; the check cannot prove GitHub freshness
until `git fetch` succeeds. For a distributed worker installed elsewhere,
check that process/import path separately.

## Explicit operator refresh, after approval

1. Stop or coordinate the hourly collector/media/analysis writer jobs.
   Review `git status --short`; refuse a dirty tree. Run the gate first.
2. Review the intended branch/release and cleanly update the code via
   `git pull --ff-only origin main`. Never use `reset --hard` to discard
   local work. Confirm the Python package imported by cron points at
   this checkout; reinstall editable package if needed.
3. Preview **both** runtime config changes via:
   `./.venv/bin/python scripts/deploy_ai26_sources.py` and
   `./.venv/bin/python scripts/deploy_ai26_study_config.py`.
   Have a maintainer explicitly approve source additions/removals, arena
   changes and other sampling choices. Do not interpret a code merge as
   that approval.
4. Only after approval run `deploy_ai26_sources.py --apply`, adding
   `--allow-removals` **only** if the exact removed identities were approved,
   then `deploy_ai26_study_config.py --apply`. The deploy scripts keep
   timestamped previous-version backups. **Do not change their guards.**
5. Re-run the staleness check, verify the deployed import path, then
   restart/check one fresh scheduled collector cycle. Confirm source drift
   is in sync. Failure to refresh the running process cannot be inferred
   solely from matching on-disk hashes.

Rollback: stop concurrent writers; restore the reviewed timestamped copies
of both runtime config files if appropriate, and `git revert` a bad code
change in a new reviewed release rather than forcing a checkout reset.
Re-run dry-runs and gate, and separately review records already collected;
restoring config does not undo collection.

## CI / repeatability

```bash
python -m pytest -q tests/test_issue_277_runtime_sync.py
```

Tests use temporary Git repositories, never the live Laskin runtime.
The checker is intentionally suitable for inclusion as a **report-only**
line in the existing daily technical report. No cron installation or
sampling change occurs in this PR.
