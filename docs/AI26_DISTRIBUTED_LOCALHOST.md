# AI26 distributed collection — WSL localhost verification and the queue-identity defect (#378)

What was verified on the **Windows laptop (WSL)** host on 2026-10-28, and the one defect the live run
exposed. The Ubuntu desktop is a different host and is **not** claimed here; Laskin's role is in
`AI26_DISTRIBUTED_LASKIN.md`.

## 1. This host's role

| Capability | Value on the WSL laptop |
| --- | --- |
| Browser / X capture | yes, through the Firefox extension (manual, human-operated); the localhost CLI cannot drive a browser |
| Non-browser collection | Bluesky and arXiv via `ai26_localhost_collect`; RSS via `laclaugpt-server-rss` |
| Queue capability declared | `non_browser` — the CLI reports browser jobs as a hard error rather than running them |
| Shared MongoDB | yes, the same plane Laskin writes to |
| CSC Allas | configured; **writes refused by the project quota** (see #373) |

## 2. What was already there

PRs #384, #386 and #387 landed the localhost queue path before this change: `--dispatch-mongo`,
`--status`, `--lease-seconds`, settle-on-failure, a guard that raises if a browser job is ever handed
to this worker, and a host-derived worker id (`<machine>-<hostname>`).

## 3. The defect the live run exposed

The queue is only a de-duplication mechanism if two hosts reading the same manifest address the **same
entry**. They did not:

| | queue identity |
| --- | --- |
| Laskin (`load_non_browser_jobs` → `job_identity`, reads `name`) | `bluesky_account:Timnit Gebru` |
| localhost collector (`_manifest_jobs`, derived from `handle`/`query`) | `bluesky_account:timnitgebru.blacksky.app` |

Measured consequence, not a hypothesis: the first live `--dispatch-mongo` cycle on this host claimed a
job (`bluesky_account:Timnit Gebru`) that matched **no** manifest row under the local identity, so the
worker settled nothing, planned nothing, and left the lease held; the same run also enqueued two
handle-shaped ids that no host can ever match again.

Fixed by `_manifest_jobs()` in `ai26_localhost_collect.py` (merged with #388): the manifest's `name` field decides the
identity, with `handle`/`query` kept only as fallbacks for a manifest without `name`. The runner's
`--worker-id` default no longer claims to be `laskin-cron` on every host.

## 4. Evidence from this host (live queue, not a fixture)

**Queue before the fixed cycle** — 34 entries, including 10 Bluesky and 10 scholarly rows that Laskin
had enqueued.

**One `--dispatch-mongo --max-jobs 1` cycle**

```json
{"dispatch": "mongodb", "machine": "laptop",
 "runs": [{"plugin": "bluesky", "source": "Timnit Gebru", "records_seen": 20,
           "records_written": 10, "duplicates_skipped": 10, "status": "ok"}]}
```

**Queue after the cycle**

| | before | after |
| --- | --- | --- |
| entries | 34 | **34** |
| new ids created by the cycle | — | **none** |
| `done` | 1 | 2 |
| active leases | 0 | 0 |

That is the property #378 asks for: the host claimed a job another machine had enqueued, collected it
once, settled it, and created no parallel identity. `scripts/ai26_worker_status.py` reports the same
plane: queue depth 32 (`done` 2), 0 active leases, 0 expired.

Cleanup done rather than hidden: the lease the pre-fix run left held was released explicitly, and the
two handle-shaped ids it created were deleted.

## 5. The Firefox/X session on this host (2026-10-28)

`scripts/start_ai26_x_capture.sh start` brought the loopback backend up and the operator opened the
dedicated AI26 Firefox profile; captures started landing immediately.

```
backend:   http://127.0.0.1:8765  (/status, /tour)   study ai26, active
windows→wsl: curl.exe http://localhost:8765/status -> 200   (WSL localhost forwarding works)
profile:   laclaugpt-ai26 (Profiles/nsu5uul4.laclaugpt-ai26), extension loaded
tour:      https://x.com/OpenAI  (group "Frontier labs and AI industry")
captures:  18 captures, 2 posts, 4 errors, 14 raw files in data/ai26/raw/x/20261028/
canonical: 2 new rows in data/ai26/normalized/x.jsonl
           https://x.com/OpenAI/status/2114780711664398349
           https://x.com/OpenAI/status/2107894999119774148
```

### The captures do not reach the shared plane, and the cause is the Allas quota

The local capture path works; the **mirror** does not. A direct scan of the mirror reproduces it:

```
SCAN ERROR: ObjectStoreError upload failed for
  projects/ai26/runs/ai26-distributed-001/raw/<sha256>.json:
  An error occurred (QuotaExceeded) when calling the PutObject operation: Unknown
```

`DistributedCaptureSink._raw_object()` uploads each capture's raw envelope to S3 *before* the record
is written to MongoDB, so a refused PUT means the record never reaches `ai26__records` (9,812 docs,
none from today) — the capture exists only on this host's disk. This is the same project-level quota
that blocks #373: `LaclauGPT-AI26` holds 36.85 GB and `LaclauGPT-Brazil26` 27.76 GB, and a 5-byte PUT
is refused in both containers.

Two ways forward, and the choice is a durability decision rather than a bug fix:

1. **Raise the quota** (CSC) and the existing mirror catches up on the next scan — no code change.
2. **Make the raw-envelope object optional**: persist the record to MongoDB with
   `raw_capture.ref` pointing at the local `data/ai26/raw/...` file and an explicit
   `raw_object_status: pending`, then upload the object when the quota allows. That keeps the evidence
   traceable but changes the durability contract, so it is not done here.

### Second defect found by this session, fixed

`JsonlDistributedMirror._save_offsets()` used `Path.replace()` on a dot-temp file; on this
WSL/OneDrive checkout that raises `FileNotFoundError` (a sync agent moves the temp file between the
write and the rename), seen three times in the startup replay. It aborted every scan after the first
synced row, leaving the offsets stale so each restart replayed the whole JSONL. Fixed with a direct
write fallback, pinned by `tests/test_issue378_mirror_offsets.py`.

## 6. Runbook (this host)

```bash
cd "$LACLAUGPT_CHECKOUT"          # the checkout that owns data/ on this host
set -a; source data/config/ai26-localhost.env; set +a

# read-only: queue depth, leases, whether this host may take browser work
.venv/bin/python -m laclaugpt_data_collection.ai26_localhost_collect --status

# one bounded cycle claiming this host's share
.venv/bin/python -m laclaugpt_data_collection.ai26_localhost_collect \
  --source-manifest data/config/ai26.sources.toml \
  --study-config data/config/ai26.yaml \
  --dispatch-mongo --max-jobs 1
```

Installing the collectors on a fresh host: `.venv/bin/python -m pip install -e '.[phase1-non-browser]'`.
Without it the plugins are absent and every claimed Bluesky/arXiv job is released with a
`ModuleNotFoundError` instead of collecting.

The AI26 cron block on this host is currently **commented out**. Enabling it is a sampling decision,
not a deployment step, so it was not switched on here.

## 7. Known gaps after this change

1. **RSS is not queue-coordinated.** `laclaugpt-server-rss` rotates its own feed window, so
   `web_source` rows (11 pending in the queue) can be fetched by more than one host. The store
   de-duplicates by canonical source identity, so the cost is wasted work rather than duplicate data.
2. **Allas archival is blocked by the project quota** — a 5-byte PUT is refused — so AI26 media and
   metadata cannot be archived from this host yet.
3. **X capture runs locally but does not reach MongoDB**, for the quota reason in §5. The browser
   half is proven; the archival half is blocked upstream.
