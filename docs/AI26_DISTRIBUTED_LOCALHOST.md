# AI26 distributed collection — WSL localhost role and runbook (#378)

What is implemented for the **Windows laptop (WSL)** host, and what was actually executed here. The
Ubuntu desktop is a separate host and is **not** claimed by this document; Laskin's role is in
`AI26_DISTRIBUTED_LASKIN.md`.

## 1. This host's role

| Capability | Value on the WSL laptop |
| --- | --- |
| Browser / X capture via Firefox | **yes** (extension → capture receiver; the runner never drives a browser) |
| Non-browser collection | yes — Bluesky and arXiv through `ai26_localhost_collect`, RSS through `laclaugpt-server-rss` |
| Queue capabilities declared | `browser`, `non_browser` |
| Queue kinds this host **executes** | `bluesky_account`, `scholarly_query` |
| Shared MongoDB | yes (the same plane Laskin uses) |
| CSC Allas | configured, but **writes are refused by the project quota** (see #373) |

Declaring `browser` and being able to *execute* a browser kind are different questions. The X path is
the Firefox extension posting into the capture receiver; nothing in the runner drives a browser. The
queue therefore keeps browser kinds out of this worker's claims even though the host advertises the
capability, because a claimed-but-unexecutable job would sit on a lease until it expired.

## 2. What was missing before this change

- `ai26_localhost_collect` ran **every** Bluesky and arXiv row in its own copy of the manifest on every
  tick. Laskin ran the same rows from the same manifest. Two hosts, one source, duplicate work.
- `dispatch_claim()` in `distributed_jobs.py` hard-coded `LASKIN_CAPABILITIES`, so a localhost could
  not declare what it is even for reporting purposes.
- The runner's default worker id was `laskin-cron` on **every** host, so the shared queue could not
  tell which machine held a lease.
- The localhost collect wrapper had no distributed option at all; only the Laskin wrapper had one.

## 3. What changed

| Change | File |
| --- | --- |
| `claim()` accepts an explicit `kinds` restriction, so a worker claims only work it can execute | `src/laclaugpt_data_collection/distributed_jobs.py` |
| `dispatch_claim()` takes `capabilities` and `executable_kinds` (defaults unchanged: Laskin-safe) | same |
| `plan_jobs()` — the localhost's share of the manifest, claimed through the shared queue | `src/laclaugpt_data_collection/ai26_localhost_collect.py` |
| `--dispatch-mongo`, `--worker-id`, `--max-jobs`, `--dispatch-lease-seconds` on the localhost collector | same |
| Each claimed job is settled: `complete` on success, `release` with a reason when a plugin fails or has nothing to run | same |
| `--capabilities {laskin,non_browser,localhost,all}` on the runner, mapped to the queue capabilities | `src/laclaugpt_data_collection/ai26_laskin_runner.py` |
| `default_worker_id()` — host-derived (`<hostname>-cron`, or `LACLAUGPT_WORKER_ID`) | same |
| `LACLAUGPT_AI26_DISTRIBUTED_JOBS=1` opt-in on the localhost wrapper, mirroring the Laskin one | `scripts/run_ai26_localhost_collect.sh` |

The default remains **manifest mode** on every host. Switching a live cron to the queue is an
operational decision, and an un-migrated host must keep behaving exactly as audited.

## 4. Runbook

```bash
cd "$LACLAUGPT_CHECKOUT"          # the checkout that owns data/ on this host
set -a; source data/config/ai26-localhost.env; set +a

# host health (read-only): queue depth, leases, whether this host may take browser work
PYTHONPATH=src python3 scripts/ai26_worker_status.py \
  --settings data/config/ai26-localhost.env --capabilities localhost

# one bounded cycle that claims its share from the shared queue
LACLAUGPT_AI26_DISTRIBUTED_JOBS=1 LACLAUGPT_AI26_WORKER_ID=blazer-cron \
  bash scripts/run_ai26_localhost_collect.sh
```

To make the queue permanent for this host, set `LACLAUGPT_AI26_DISTRIBUTED_JOBS=1` in the untracked
runtime env (`data/config/ai26-localhost.env`) and re-install the cron block:

```bash
bash scripts/install_cron_ai26.sh          # AI26 cron entries are commented out on this host today
```

## 5. Collected evidence on this host (2026-10-28)

Host `BLAZER` (WSL), shared MongoDB plane, live queue — not a fixture.

**Health before the cycle**

```
MongoDB: reachable
queue depth: 26  {'pending': 26}
by kind: {'mastodon_account': 2, 'scholarly_query': 2, 'web_source': 11, 'bluesky_account': 11}
active leases: 0  expired: 0
this host may take browser work: yes
```

**One `--dispatch-mongo` cycle** (`--max-jobs 1`, worker `blazer-cron`)

```json
{"dispatch": "mongo", "jobs_planned": 7, "jobs_claimed": 1,
 "runs": [{"plugin": "bluesky", "source": "Emily M. Bender", "records_seen": 20,
           "records_written": 10, "duplicates_skipped": 10, "warnings": []}],
 "worker_id": "blazer-cron"}
```

A manifest row declared by Laskin's queue was claimed here, collected, written once (10 duplicates
skipped by the store, not by luck) and settled as `done`.

**Queue after the cycle**

```
queue depth: 33  {'pending': 33, 'done': 1}
by kind: {'scholarly_query': 10, 'bluesky_account': 10, 'web_source': 11, 'mastodon_account': 2}
active leases: 0  expired: 0
```

No browser kind exists in the queue and none was claimed. Two operational notes from this run, both
fixed rather than hidden:

- the first cycle ran **before** the identity fix and left one lease held (`bluesky_account:Timnit
  Gebru`); it was released with `store.release(..., error="local run before identity fix")` rather
  than waited out.
- that same run enqueued two handle-shaped job ids (`bluesky_account:timnitgebru.blacksky.app`,
  `bluesky_account:emilymbender.bsky.social`). No manifest row can ever match them, so they were
  deleted; the identity is now `kind:name`, the field the Laskin runner enqueues with.

**Tests** — `1129 passed, 4 skipped` for the full suite, including
`tests/test_issue378_localhost_queue.py` (5 tests: manifest mode vs queue mode, browser kinds never
claimed, stable identity across hosts) and the extended `tests/test_distributed_jobs.py`.

## 6. Known gaps after this change

1. **RSS is not queue-coordinated.** `laclaugpt-server-rss` still rotates its own feed window, so
   `web_source` rows can be fetched by both Laskin and this host. Records are deduplicated by canonical
   source identity in the store, so this is wasted work rather than duplicated data — and it is the
   next slice, not something this change pretends to have solved.
2. **Allas archival is blocked by the project quota** (a 5-byte PUT is refused), so AI26 media and
   metadata cannot be archived from this host yet.
3. **The Firefox capture path is verified only as a component**: the receiver and the extension are a
   manual, human-operated session; nothing here proves a live X capture on this machine.
