# AI26 localhost collection with Tomi's Firefox — Laskin runbook (#433)

What the AI26 collection path actually is on **Laskin** (this machine), which parts an agent can
verify alone, and the one part that waits for Tomi. Written from measurement on 2026-11-16, not from
the general guide: the generic `AI26_FIREFOX_BROWSER_COLLECTION.md` describes the repository's own
`ai26_browser` backend, while Laskin runs the **`collector.firefox` backend as a systemd service**.

## 1. The two halves, and who owns which

| half | what runs | verified by |
| --- | --- | --- |
| **Data plane** | shared MongoDB (`ai26__records`), Redis, S3 bucket `LaclauGPT-AI26` | agent — `scripts/ai26_jobs_smoke.py`, `ai26_browser check` |
| **Browser capture** | `ai26-capture.service` → `collector.firefox.firefox_backend` on `:8766`; Firefox (snap) with the capture extension, logged into the platforms | agent can verify the backend; **Tomi** provides the logged-in Firefox session |

## 2. Data plane

```bash
cd /mnt/workspace/LaclauGPT-Data-Collection
set -a; . <private>/analysis/ai26/laskin.env; set +a        # never commit this file

# queue + database round trip in a throwaway database that is dropped afterwards
.venv/bin/python scripts/ai26_jobs_smoke.py --settings <private>/analysis/ai26/laskin.env

# identity, remote control plane, collection names
export AI26_CONFIG=<private>/collection/ai26/ai26.private.yaml
export LACLAUGPT_PRIVATE_CONFIG_DIR=<private>/collection   # see the note below
set -a; . <private>/analysis/ai26/laskin.env; set +a
.venv/bin/python -m laclaugpt_data_collection.ai26_browser check
```

**The `LACLAUGPT_PRIVATE_CONFIG_DIR` note.** `ai26_browser` refuses a study config that does not live
under an ignored runtime root and names the allowed roots in the error. If the private config sits
elsewhere (on Laskin it is `<private>/collection/ai26/`), set `LACLAUGPT_PRIVATE_CONFIG_DIR` to its
parent — the check otherwise exits with a `ValueError` that looks like a broken install.

Measured 2026-11-16: smoke **9/9** (enqueue, Laskin refuses browser work, localhost claims it, no job
claimed twice, expired leases reaped and reclaimable, completion idempotent, status reporting);
`ai26_browser check` → `"status": "ok"` with `mongodb_collection: ai26__records`, `redis: ok`.

## 3. Browser capture backend

| property | measured value |
| --- | --- |
| unit | `ai26-capture.service` (**user** manager, not system) |
| process | `python3 -m collector.firefox.firefox_backend --host <tailscale> --port 8766` |
| checkout | `/home/tomi/laclaugpt-ai26` |
| data root | `/home/tomi/laclaugpt-ai26-data` |
| status endpoint | `GET http://<tailscale>:8766/status` → `study`, `run_id`, `active`, `seen_total`, counters |

The backend binds the **Tailscale address**, not loopback, so `curl 127.0.0.1:8766` fails while the
service is healthy. Probe the address the unit binds:

```bash
curl -s http://<tailscale>:8766/status
```

`scripts/ai26_localhost_readiness.py` tries an explicit URL, then loopback, then `AI26_BIND_HOST`, and
reports which one answered.

## 4. Firefox — Tomi's part

**The agent does not create, modify or reset the Firefox profile.** Firefox is the snap build
(159.0-1), profile directory `~/snap/firefox/common/.mozilla/firefox`. The steps are Tomi's:

1. Launch the AI26 profile (`about:profiles`), keeping it separate from Brazil26.
2. `about:debugging#/runtime/this-firefox` → **Load Temporary Add-on** → `browser/firefox/manifest.json`.
3. Log into the platforms the study collects from, in that profile.
4. Say **"Firefox is ready"**. Only then does the agent run the browser-dependent smoke test.

## 5. The handoff checkpoint

```bash
# before Tomi confirms — expected to end with one BLOCKED line, exit 0
python scripts/ai26_localhost_readiness.py

# after Tomi confirms
python scripts/ai26_localhost_readiness.py --firefox-ready --json
```

`BLOCKED` is not `FAIL`: the readiness script exits non-zero only for real failures, so a pending
handoff cannot be mistaken for a broken deployment, and cannot be quietly reported as passing either.

## 6. Bounded smoke test (only after §4)

Keep it small and inspectable; do not start an open-ended crawl.

```bash
# one capture cycle through the running backend, small budget
python -m laclaugpt_data_collection.ai26_localhost_collect --dispatch-mongo --max-jobs 1
```

Then verify what landed, read-only, and record: records written vs seen, duplicates skipped, the
`provenance`/`run_id` written with each record, and that a second identical cycle writes nothing new
(idempotency). Row-level detail stays in the private repository; the issue gets counts only.

### 6a. The ingest half of that smoke test, executed 2026-11-16

The RSS CLI path needs no browser, so it was run — bounded, against the centralized store, and read
back. This does not stand in for the browser half in §4; it proves that what the browser will hand to
the same sink lands, deduplicates and reads back.

```
$ laclaugpt-server-rss --study-config data/config/ai26.yaml \
    --source-manifest data/config/ai26.sources.toml \
    --max-feeds 4 --per-feed-limit 4 --limit 4 --json
{"status": "ok", "collection_id": "ai26", "feeds_polled": 4,
 "records_collected": 14, "records_synced": 4, "records_new": 1, "records_updated": 3,
 "skipped_before_publication_floor": 10,
 "storage_mode": "distributed", "storage_target": "ai26__records", "errors": []}
```

Read back afterwards: `ai26__records` went **11,190 → 11,191**, and the inserted rows carry
`handoff.status=ready`, a `revision`, `project=ai26`, `collection=ai26`, `schema=1.1.0`.

The same command run again immediately:

```
{"records_collected": 14, "records_synced": 4, "records_new": 0, "records_updated": 4}
```

Zero new. Across the whole collection at that moment: **0 duplicated `handoff_key` values** — the
`handoff_key` and `routing_source_unique` indexes are what make that structural rather than hopeful.

Two operational numbers from the same session, because they change how the start path is read:

* **The port on this host is 8765**, not the 8766 default — `LACLAUGPT_BROWSER_PORT` in the private
  runtime env decides, exactly as §4 says.
* **A healthy start looks like a hang.** Constructing the distributed sink takes ~33 s here, then the
  backend replays its local mirror before binding: the first `/status` answered ~90 s after `start`.
  A wrapper that gives up at 60 s reports a working backend as a failure. The script prints
  `still starting (Ns): mirror offset …`, so wait for `3/3`.

## 7. Stop and resume

```bash
systemctl --user stop ai26-capture.service      # capture backend only
systemctl --user start ai26-capture.service
systemctl --user status ai26-capture.service
```

Stopping the backend does not touch the data plane or the analysis cron. Resume is the same command;
the collector keeps its own state under the data root, and the queue leases expire on their own.

## 8. Known issues on this host (filed, not fixed here)

- **`ai26-export.service` has been `failed` since 2026-10-11** (1 month 5 days): the dashboard JSONL
  export after each analysis tick has not run. Filed separately.
- **The running capture backend predates the current code**: it has been up 22 days, `/status` reports
  an empty `git_commit`, and `GET /ping` — present in the checkout — returns 404 from the running
  process. Treat it as *merged but not deployed*: restart it from the reviewed checkout before
  drawing conclusions about capture behaviour. *Updated 2026-11-16: it has since been restarted from
  the reviewed checkout and `/status` now reports `git_commit=6b2e9f4`, `active=true`, `study=ai26`,
  with `/status` and `/tour` both 200. Note that this SHA is the checkout's, so it still does not prove
  a clean tree — keep the working tree clean before a session or the reported commit proves nothing.*
- **Bind address**: the unit binds the Tailscale interface. The general guide says the backend must
  bind loopback only; that discrepancy is a decision for Tomi (loopback breaks capture if Firefox runs
  on another machine).

## 9. What is not claimed

No browser-dependent capture has been executed here. The smoke test in §6 is **BLOCKED** until Tomi
confirms Firefox, and this runbook reports it as blocked rather than as passed.

What *is* claimed is §6a: the ingest path was exercised against the centralized store with a bounded
run, a record was inserted and read back, and an identical re-run added nothing. Browser capture
remains the one unverified link, and it needs the handoff in §5 to happen first.
