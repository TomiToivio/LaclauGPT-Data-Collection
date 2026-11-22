# AI26 source-manifest deployment (issue #206)

The running collection reads a **deployed** source manifest from runtime data:

```
data/config/ai26.sources.toml        # gitignored runtime config, what the pipeline reads
configs/studies/ai26.sources.example.toml   # the audited plan, in Git
```

`data/` is gitignored by design (see `docs/RUNTIME_DATA.md`), so the deployed file
is operational state, not a tracked artefact. The consequence is that a source can
be audited, verified and committed **and still never be collected**, because the
running set only changes when the deployed file changes.

Measured 2026-10-09: deployed **54** sources vs tracked **78** — 24 audited sources
with no records at all, including the Finnish public-interest feeds (`sitra`,
`etla`, `sttk`, `teollisuusliitto`), the EU rights feeds (`edri`, `eff_updates`)
and the configured X handles `AINowInstitute` / `AdaLovelaceInst`.

## Detect drift

Read-only, reports only (never writes):

```bash
python -m laclaugpt_data_collection.cli manifest-drift \
    --deployed data/config/ai26.sources.toml \
    --tracked  configs/studies/ai26.sources.example.toml
```

Add `--fail-on-drift` to gate a schedule on it. The hourly collect cycle also carries
a `manifest_drift` field (report-only), and `scripts/run_ai26_laskin_collect.sh`
passes the tracked plan by default, so a drift summary lands in the cycle log.

## Deploy the audited plan

`scripts/deploy_ai26_sources.py` is **dry-run by default**:

```bash
# 1. review the exact change
python scripts/deploy_ai26_sources.py

# 2. apply, creating a timestamped backup first
python scripts/deploy_ai26_sources.py --apply
```

Guards, so a deployment cannot silently drop coverage:

- refuses a **symlinked** manifest on either side;
- refuses if **any active deployed source identity would disappear**, unless
  `--allow-removals` is passed explicitly;
- writes through a temporary file and only then replaces, so an interrupted run
  cannot leave a half-written manifest;
- keeps a `*.backup-<UTC-stamp>` copy of the previous file;
- prints both sha256 digests, so the deployed state is provable.

> `--allow-removals` is for a **deliberate** coverage decision. Check whether an
> apparent removal is really a *kind change* first: `openai_news` moved from
> `[[web_source]]` to `[[feed]]` (its official RSS feed) under issue #170, and the
> helper reports that as a removal because the identity key includes the kind. The
> source is not lost.

## Canonical roster and recovery (#456)

The **tracked** `configs/studies/ai26.sources.example.toml` is the public audited
source roster. The live `data/config/ai26.sources.toml` remains an ignored,
recoverable deployment copy, **not** a second source of truth. Do not edit it to
introduce lasting source additions without first auditing those rows in Git.
If a host is lost, redeploy from the tracked plan using the dry-run and guarded
apply steps above; preserve any separate private-only source overlays in the
private configuration repository, not in this public checkout. No host-only
roster is guaranteed to be recoverable without such an audit.

On 2026-11-22 issue #456 recorded two intentionally deployed but unaudited
Network School `web_source` rows. Those are now declared in the tracked plan:
`https://ns.com/podcast` and `https://ns.com/podcast/roy` (text-first; no
media downloads). **Before applying on Laskin**, compare the two live rows to
the audited metadata (particularly `arena`, `priority`, and `transcript`),
review the full diff, and keep the live configuration backed up. This repository
change does not itself change the currently running host. After deployment,
run `manifest-drift --fail-on-drift` against the two actual files and confirm
`in_sync: true` in a new cycle log. Any remaining drift is an unresolved
sampling or deployment decision, not permission to suppress the alarm.

## Recommended cadence

Redeploy **whenever `configs/studies/ai26.sources.example.toml` changes** — the
tracked plan is the audited source of truth, and the deployed file is a copy of it.
The drift report makes a forgotten redeploy visible on the next cycle rather than
two weeks later.

## Precedent

On 2026-10-09 the deployed manifest was brought back into sync with the plan using
this procedure: **26 active sources added**, the one reported removal being the
`openai_news` kind change above. After applying, `manifest-drift` reports in sync
and the deployed set holds 37 feeds / 30 non-browser jobs, with every source
reachable across one rotation of the collector window.
