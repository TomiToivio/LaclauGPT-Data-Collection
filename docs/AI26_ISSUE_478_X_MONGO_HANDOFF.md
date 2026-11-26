# AI26 localhost X → shared MongoDB → Laskin (#478)

Use the same AI26 database and study config as Laskin on both WSL and Ubuntu.
Do not run a new MongoDB instance for this workflow. The browser capture remains
loopback-only. Firefox setup and X browsing are researcher-controlled.

## On each localhost

1. Update the existing checkout and install its dependencies (`python -m pip install
   -e '.[distributed]'` in the existing virtual environment).
2. Set the following in the existing ignored `data/config/ai26-localhost.env`.
   Use the actual private values from the Laskin deployment, not new credentials:
   `LACLAUGPT_MONGODB_URI`, `LACLAUGPT_MONGODB_DATABASE`,
   `LACLAUGPT_PRIVATE_CONFIG_DIR`, `LACLAUGPT_PROJECT_ID=ai26`,
   `LACLAUGPT_RECORD_BACKEND=mongodb`. Give each host separate local data roots
   and use existing machine provenance (laptop / custom). Keep the same study
   manifest and configure the extension with the printed loopback port.
   Redis settings are optional coordination; the browser text mirror retains raw
   JSON in MongoDB and does not require Allas or download media.
3. Run:

   ```bash
   bash scripts/start_ai26_x_capture.sh --dry-run
   bash scripts/start_ai26_x_capture.sh start
   bash scripts/start_ai26_x_capture.sh status
   ```

   Status exit 3 means central mirroring is not verified. Do not mistake local
   capture counters for central persistence. A private log can diagnose failures.
   Use the existing managed service instead of starting a duplicate process.
4. Tomi opens the approved Firefox profile and visits a declared X source.
   Check status again. To resume after interruption, stop the launcher-owned
   process then start it again; the JSONL mirror retries unsynced rows from
   its checkpoint. Do not delete or manually edit checkpoints.

   ```bash
   bash scripts/start_ai26_x_capture.sh stop
   bash scripts/start_ai26_x_capture.sh start
   ```

## Verify on Laskin (read-only)

Use the private Mongo configuration used by the analysis worker, not an arbitrary
database on the localhost. Record the before/after counts on each host and select
one newly captured canonical source URL privately to trace through the stages.

```bash
# Load trusted private runtime environment before running; never print its values.
python - <<'PY'
import os
from pymongo import MongoClient

client = MongoClient(os.environ["LACLAUGPT_MONGODB_URI"], serverSelectionTimeoutMS=5000)
db = client[os.environ["LACLAUGPT_MONGODB_DATABASE"]]
x = db["ai26__records"]
query = {"project_id": "ai26", "source.platform": "x"}
print("X records", x.count_documents(query))
for status in ("ready", "excluded", "waiting_media"):
    print(status, x.count_documents({**query, "handoff.status": status}))
print("analysis result total", db["ai26__analysis_results"].count_documents({}))
PY
```

Verify one new post from each host by canonical URL, machine provenance, and
handoff key: source exists once, publication time and arena match the manifest,
handoff is ready if eligible, matching analysis result is complete, and the
single existing dashboard on port 8504 displays it after refresh. Recollect one
post and check the canonical identity count remains one. Preserve the Phase 1
eligibility gate (older or undated material may legitimately be excluded).
Do not modify sampling to force a successful smoke test.

| Acceptance | WSL | Ubuntu | Laskin/dashboard |
|---|---|---|---|
| Shared Mongo read-back | NOT RUN | NOT RUN | NOT RUN |
| Duplicate identity check | NOT RUN | NOT RUN | NOT RUN |
| Completed analysis | — | — | NOT RUN |
| Dashboard rendering | — | — | NOT RUN |

Publish sanitized counts, timestamps, statuses and commit only; never post URLs of
sampled records, raw contents, credentials, or private endpoints. If analysis
is waiting for GPU capacity, record the backlog separately rather than claiming
a collection failure. Agents without machine access may run synthetic tests and
review the code; only agents with host access can fill the live acceptance table.
