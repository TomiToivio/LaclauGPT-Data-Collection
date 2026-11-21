# AI26 station: what was repaired on 2026-11-21

The station's issues #436–#443 all traced back to two outages plus one deliberate omission.
This records what changed on the hosts, because those changes are runtime state and would
otherwise survive only in this repository's issue tracker.

## MongoDB (SpectacleScraper) — #439, #440, #443

`mongod` had been **OOM-killed on 2026-11-16 18:45 UTC** and, with no restart policy, stayed
dead for four days. Every AI26 stage failed on the store: collect exited `runner_status=1`,
media recorded failures, and the analysis worker refused to claim tasks in preflight. The
journal's own words:

```
Nov 16 18:45:32 spectaclescraper mongod.service: A process of this unit has been killed by the OOM killer.
mongod.service: Failed with result 'oom-kill'.
```

The host has **3 GB RAM** shared with three Streamlit dashboards, MariaDB and Redis, so the
default WiredTiger cache (50 % of RAM − 1 GB) could not hold. Two changes:

| file | change |
| --- | --- |
| `/etc/mongod.conf` | `storage.wiredTiger.engineConfig.cacheSizeGB: 0.5` (backup: `mongod.conf.bak-<ts>`) |
| `/etc/systemd/system/mongod.service.d/restart.conf` | `Restart=always`, `RestartSec=10`, `OOMPolicy=continue` |

Verified after restart: `mongod` active, listening on 27017, `spectacleScraper` database intact
(226 collections, `ai26__analysis_results` 5 311 documents, `ai26__jobs` 37), and a collect run
through the station's own wrapper returned `collected=120 synced=89 errors=0`.

## Dashboard export (Laskin) — #436

`ai26-export.service` had failed since 2026-10-11 with two stacked faults:

1. `_dashboard_record()` validated every annotation with the interchange model, which requires
   `formation_original` to be a **list**; older annotations store it as a string, so the export
   aborted on the first such record.
2. The unit's `ExecStartPre` truncated the three live JSONL files *before* the export ran, so
   the failure left the dashboard with **three empty files** rather than stale ones.

Repaired in `/mnt/workspace/laclaugpt-private/ai26_runtime/export_dashboard_jsonl.py`
(backup `*.bak-436`):

* a dual-shape normaliser coerces `formation_original` string → list;
* a record that still fails to validate is skipped **and named** (`skipped N annotation(s)`)
  instead of costing the whole export;
* the truncating `ExecStartPre` is removed from the unit (backup `ai26-export.service.bak-436`)
  — the script already writes to a temp file and `os.replace()`s, so truncation was redundant
  *and* destructive;
* `ai26-export.timer` was `inactive` and never enabled, which is why nothing retried it. It is
  now `enabled` and `active` (`OnCalendar=*:1/10`).

Verified: a manual run wrote `{'elites': 2080, 'grassroots': 385, 'parliamentary': 2}` — 52.8 MB,
10.4 MB and 52.8 KB — and a JSON parse of all 2 467 lines found zero unparseable records.

## Media stage (Laskin crontab) — #443

The `:30` media stage failed 120 consecutive cycles on Allas `QuotaExceeded`, and the study
owner's 2026-11-16 decision is that AI26 collects no multimodal data and Allas is not needed.
A stage whose storage backend has been deliberately switched off does not belong on an hourly
cron, so the line is commented out in Laskin's crontab with the reason recorded above it. The
local station's equivalent line was already commented out.

Re-enable by uncommenting that line when multimodal collection returns.
