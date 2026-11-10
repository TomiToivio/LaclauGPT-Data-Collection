# AI26 distributed collection — Laskin role, queue and runbook (#378)

What is actually implemented and what is not, measured on Laskin on 2026-10-28. This document does not
claim that the WSL laptop or the Ubuntu desktop are deployed: nobody has run this there, and the issue
forbids implying otherwise.

## 1. Host roles

| Host | Browser/X capture | Non-browser collection | Queue capability |
| --- | --- | --- | --- |
| Windows laptop (WSL) | yes | yes | `browser`, `non_browser` |
| Ubuntu desktop | yes | yes | `browser`, `non_browser` |
| Laskin (this server) | **no** | yes | `non_browser` only |

Laskin runs a Firefox **capture receiver** (`ai26-capture.service`, port 8766) that accepts POSTs from
the extension running on the two localhosts. It never launches a browser: verified by checking for
`firefox`/`geckodriver` processes, which are absent while the service is active. Receiving captures is
not browser automation; launching one would be.

## 2. What was missing, and what changed

Until now every host picked work from its own copy of `data/config/ai26.sources.toml`: the manifest is
filtered to non-browser tables and a rotating window is taken. That is a *local* decision, so nothing
stopped two hosts from claiming the same job, and "Laskin does no browser work" rested on the shape of
one TOML file rather than on the queue.

Added in this change:

- **`src/laclaugpt_data_collection/distributed_jobs.py`** — a lease-based job queue over the shared
  MongoDB plane. Capability enforcement lives in the claim *query*, not in the caller: a worker
  without the `browser` capability claims through a filter carrying
  `kind: {$nin: BROWSER_REQUIRED_KINDS}`, so a browser job cannot be handed to Laskin even if a
  caller asks for one. A future browser-only kind is therefore denied by default.
- **Atomic claims** — one `find_one_and_update` per job, ordered by
  `(priority, next_run_at, created_at, _id)`. MongoDB's per-document atomicity is the whole
  concurrency argument, so two workers cannot win the same job.

  The order used to be `(priority, created_at)`, and every job in the AI26 queue was bulk-enqueued
  from a single clock read — a total tie. The winner was therefore whatever index the planner
  picked, and `(status, kind, …)` sorts `bluesky_account` before `web_source`: eleven web sources
  never ran once in twelve days while six account jobs were claimed every hour (#406).
  `next_run_at` ascending puts a job that has never run first (Mongo sorts a missing field before
  numbers) and a job that has waited longest next; `_id` ends the sort, so the answer is a rule and
  not a plan.

- **Round-robin across kinds.** `claim()` takes one job per kind per round instead of the cheapest
  `limit` in one flat order, so a stratum cannot be crowded out by a bigger one in the same
  priority. With `--max-jobs 6` and four claimable kinds, every kind is reached in the first round;
  within a kind the order is the one above, so the longest-waiting source goes first (#405).

- **Deferral is not failure.** The cycle claims `--max-jobs` and then stops at the tick's record
  limit; the jobs it never started go back through `defer()`, which refunds the attempt the claim
  spent and leaves `next_run_at` alone. Through `release()` they were charged a full `poll_seconds`,
  which is how a capacity limit became a source's permanent cadence and admitted two P1 Bluesky
  sources once a day while their peers ran every other cycle (#405).

- **`claimable_by_kind` per cycle.** Each cycle now reports how many jobs it *could* still claim,
  per kind. Without it, eleven sources that had never been claimed looked exactly like an idle
  queue: fourteen cycles in a row said `ok` with `deferred_by_tick_limit: 0` (#406).
- **Leases with expiry** — a machine that dies mid-job stops holding it; `reap_expired()` returns the
  work to the queue, so recovery does not need an operator. Attempts are bounded, so a job that
  crashes repeatedly parks itself as `failed` instead of spinning.
- **Idempotent enqueue** keyed on `job_id`, so re-enqueuing the manifest after a restart does not
  duplicate the queue.
- **`scripts/ai26_worker_status.py`** — operator view: reachability, queue depth by status and kind,
  active and expired leases, workers holding them, and whether this host may take browser work. No
  payloads, no credentials.
- **`scripts/ai26_jobs_smoke.py`** — end-to-end proof against the real MongoDB that the routing and
  lease rules hold, run entirely in a throwaway collection that is dropped afterwards.

## 3. Verified on Laskin (2026-10-28)

`python scripts/ai26_jobs_smoke.py --settings <private ai26 env>` against the shared MongoDB:

```
PASS  mongo reachable                 ping ok
PASS  enqueue                         3 jobs queued
PASS  laskin refused browser work     claimed=['w1']
PASS  localhost claimed browser work  claimed=['x1', 'ig1']
PASS  no job claimed twice            disjoint claims
PASS  expired leases reaped           reaped=3
PASS  reaped work reclaimable         w1 reclaimed
PASS  completion idempotent           second complete is a no-op
PASS  status reports queue            {'pending': 2, 'done': 1}

9/9 checks passed; ai26_smoke_jobs_<id> dropped after run
```

`scripts/ai26_worker_status.py` against the same settings reports the jobs collection as reachable and
empty, which is the expected state before the first dispatch.

A permission fact worth recording: the collection's MongoDB user **cannot create or drop databases**
(`dropDatabase` returns `Unauthorized`). The smoke therefore uses a throwaway *collection* inside the
authorized database, and the queue must not assume it can create a database.

## 4. Queue wiring — opt-in, not yet the live default

`ai26_laskin_runner.py` now takes `--dispatch-mongo` (and `--dispatch-lease-seconds`). With it, the
runner enqueues the manifest, claims work from the shared queue, and settles each job: `complete` on a
successful source, `release` on error, blocked or deferred-by-tick-limit — so a claimed job never sits
on a dead lease.

The wrapper exposes it as `LACLAUGPT_AI26_DISTRIBUTED_JOBS=1` (default off), because switching the live
cron is an operational decision, not a code decision. **Until that variable is set, the cron still
slices the local manifest** and the queue is unused by the running pipeline.

Verified against the live queue with the real manifest (26 non-browser rows):

```
manifest non-browser rows: 26  kinds: ['bluesky_account','mastodon_account','scholarly_query','web_source']
new rows enqueued: 26
claimed by laskin: [('bluesky_account','Timnit Gebru'), ('web_source','anthropic_news'), ...]
queue: {'pending': 26}  depth 26
browser kinds queued: []
```

Those 26 are parked as pending, which is the intended state before the switch is flipped. No collecting
cycle has been run with the flag yet.
- **AI26 media has no Allas archival step.** Brazil26 has one (#373); AI26 does not. The Allas project
  quota is currently **exhausted** — even a 30-byte write returns `403 QuotaExceeded` — so an AI26
  archival run could not complete today even if it existed. This is the same blocker recorded on #373.
- **WSL laptop and Ubuntu desktop are not deployed or verified** from here.
- **Health reporting is per-host and on demand.** There is no cross-host dashboard, and no worker
  heartbeat registry beyond the leases that workers hold.

## 5. Laskin runbook

Status of the collection worker:

```bash
python scripts/ai26_worker_status.py \
  --settings <private ai26 env> \
  --capabilities laskin
```

Smoke-test the queue on this host (safe: throwaway collection, dropped afterwards):

```bash
python scripts/ai26_jobs_smoke.py --settings <private ai26 env>
```

Existing collection jobs on Laskin are cron-driven: `run_ai26_laskin_collect.sh` every 10 minutes and
`run_ai26_laskin_media.sh` every 30. Logs live under `data/logs/`. Stop them by removing the crontab
lines; nothing in this change alters or restarts them.

Rules that must hold on this host:

1. Never start Firefox, geckodriver, Playwright or any desktop browser session.
2. Run collection with `--capabilities laskin` so browser kinds are withheld.
3. Keep AI26 settings in the private repository; never commit the env file.

## Safety reconciliation for PR #384

The main branch already uses `--dispatch-mongo` with `LACLAUGPT_AI26_DISTRIBUTED_JOBS=1`. Do not run a second independent `--queue` path. Laskin now claims only explicitly classified `NON_BROWSER_KINDS`: unclassified kinds (including future browser kinds) cannot be dispatched to a non-browser worker. This retains the newer shared dispatch implementation while incorporating #384's fail-closed capability rule.
