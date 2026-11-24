# AI26 X bridge target drift audit (#470)

The AI26 X replay bridge is an independent ingestion path, not a source added
to the ordinary collection manifest by default. Comparing the deployed and
tracked TOML manifests alone **cannot** establish that all bridge sources are
declared. Issue #470 observed 609 records from 11 X handles with no arena,
platform or source-name attribution.

This patch adds a **read-only** optional check. It does not decide which
accounts belong in the paper's sampling frame, assign arenas or change stored
records. Source inclusion and any backfill remain human research decisions.

## Operator procedure

Export the *actual* target handles from the separately operated X bridge
into a **private** UTF-8 JSON array under `data/`, for example:

```json
["@SyntheticResearcher", "SyntheticInstitute"]
```

These example handles are fictional; do not copy this fixture to production.
Use the bridge's real target inventory, not a list inferred from the observed
corpus. Run:

```bash
python -m laclaugpt_data_collection.cli manifest-drift \
  --deployed data/config/ai26.sources.toml \
  --tracked configs/studies/ai26.sources.example.toml \
  --bridge-targets data/config/ai26-x-bridge-targets.json \
  --fail-on-drift
```

The report adds `x_bridge.checked`, `bridge_target_count`,
`undeclared_bridge_handles`, `undeployed_bridge_handles`, `in_sync` and
`sampling_decision_required`. Handles are compared case-insensitively,
ignoring an initial `@`. An omitted bridge file means **not checked**, not
"all bridge sources accounted for". A supplied missing, malformed or
duplicated list fails rather than inventing a clean result.

To include the same audit in the hourly Laskin collection log, explicitly set
`LACLAUGPT_AI26_X_BRIDGE_TARGETS` to that private file path in the runtime
environment. The wrapper does not create, schedule or edit an X bridge or
authenticate to X. The collection runner reports audit errors without aborting
other non-browser jobs.

## Human decision and existing records

An operator should review the resulting undeclared handles and choose either
(a) explicitly declare approved samples and plan a *separate*, bounded,
audited backfill, or (b) maintain a separately documented exploratory stratum
with **no inferred arena**. No collection method or filename can substitute
for that sampling decision. Do not silently classify these 609 records as
elites merely because the observed accounts are prominent.

The target-file comparison checks current **target-list coverage**, not the
completeness or correctness of historical stored metadata. Re-run a read-only
`corpus-audit` against MongoDB to verify missing arena/platform/source-name
counts after a separately authorized remediation. Historical bridge activity
may need its own provenance inventory even when today's targets match.
