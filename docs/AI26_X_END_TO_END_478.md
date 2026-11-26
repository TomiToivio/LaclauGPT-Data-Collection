# AI26 localhost X handoff and acceptance (#478)

Run on **each** Ubuntu desktop and Windows WSL collection host, using that
host's existing checkout, private AI26 environment and Tomi-managed Firefox
profile. Do not run the browser on Laskin. The canonical sink is
`ai26__records` in the same configured MongoDB database used by Analysis;
local files are a retry/evidence spool, not the authoritative corpus.

## Setup and inventory per host

```bash
cd /path/to/LaclauGPT-Data-Collection
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[distributed]'
export LACLAUGPT_ENV_FILE=/path/to/private/ai26-localhost.env
export LACLAUGPT_STUDY_CONFIG=/path/to/private/ai26.yaml
# Confirm these private settings against the existing Laskin deployment:
# LACLAUGPT_MONGODB_URI, LACLAUGPT_MONGODB_DATABASE
bash scripts/start_ai26_x_capture.sh --dry-run
bash scripts/start_ai26_x_capture.sh status
crontab -l
```

Inspect existing cron/services and bridge configuration locally; do not publish
their contents, private endpoints or targets. Compare actual bridge targets
using [the #470 audit](AI26_X_BRIDGE_DRIFT_470.md). Do not infer arenas.
On WSL verify Windows Firefox can reach the actual loopback port printed by
the launcher; on Ubuntu use the same local port check.

## Start, status, resume and stop

```bash
bash scripts/start_ai26_x_capture.sh start
bash scripts/start_ai26_x_capture.sh status
bash scripts/run_ai26_localhost_sync.sh
bash scripts/start_ai26_x_capture.sh stop
```

Start only one backend per host and do not stop an independently managed
service. Tomi loads the extension and visits one approved source manually.
Follow [the #433 acceptance procedure](AI26_ISSUE_433_LOCALHOST_FIREFOX_HANDOFF.md)
for the exact port, mirror counters, error handling, restart and read-back.
Do not reset sync offsets or treat local capture as successful central ingestion.

## Repair existing X text handoffs

The #450 text-only directive means an eligible AI26 X post with nonempty text
and only supplementary photo/image/video/animated GIF references need not
wait for media downloads. The handoff reason is `ai26_x_text_only`. References,
source revision, idempotency key, publication floor, sampling and other
eligibility checks remain unchanged. Required/unknown media and PDF refs
retain their original gate. No schema change or media download is involved.

From an authorized deployment host, activate the existing private environment
and confirm the database matches Analysis. Preview, then explicitly apply
the bounded envelope-only repair:

```bash
set -a
source "$LACLAUGPT_ENV_FILE"
set +a
python scripts/reconcile_ai26_x_text_handoffs.py --limit 1000
python scripts/reconcile_ai26_x_text_handoffs.py --limit 1000 --apply
python scripts/reconcile_ai26_x_text_handoffs.py --limit 1000
```

The repair touches only still-waiting AI26 X handoff envelopes, never the
canonical text or analysis results. Counts are sanitized; the final preview
should show zero eligible within the scanned batch. Increase the scan bound
if unresolved required refs mask additional records. Investigate concurrent
conflicts before repeating. Never run the disabled media cron to fix this.

## Live acceptance evidence

Keep source identifiers private; record only counts and timestamps in issue
comments. For each host capture one new in-scope X post and verify it exists
in shared MongoDB, including source and native identity, text, author, time,
language and evidenced sampling attribution. Repeat capture and verify one
canonical identity, stable revision for identical inputs, no duplicate analysis.
Track X record counts, ready/waiting/excluded counts, analysis pending/failed/
completed counts and last successful timestamps; trace each private source
identity to its analysis output and the existing single AI26 dashboard.
Check X/arena filtering and refresh. Distinguish bridge failure from Analysis
GPU capacity (#577) and dashboard refresh. Do not start another dashboard.

| Check | Ubuntu | Windows WSL |
| --- | --- | --- |
| Private shared database identity verified | NOT RUN | NOT RUN |
| New X capture and MongoDB read-back | NOT RUN | NOT RUN |
| Recollect and dedup | NOT RUN | NOT RUN |
| Completed analysis and dashboard representation | NOT RUN | NOT RUN |

Synthetic tests do not satisfy live acceptance.
