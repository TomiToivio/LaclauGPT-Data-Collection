# Brazil26 localhost Phase 1 operations

Brazil26 uses the same canonical **Collection → Analysis → Visualization** pipeline as AI26. The study identity is always `collection_id=brazil26`; browser and non-browser collectors share `CanonicalRecord` and the general `docs/ANALYSIS_HANDOFF.md` contract.

Install:

```bash
bash scripts/install_common.sh
bash scripts/install_brazil26.sh
```

The installer copies public-safe defaults to `data/config/`: a synthetic study YAML, a bounded institutional source manifest and the localhost environment template. Live candidate/party/account overlays, credentials, cookies and private endpoints stay in `LaclauGPT-Private/collection/brazil26/`.

## Activation gate

The legacy private study file is `LaclauGPT-Private/collection/brazil26/brazil-election-2026.yaml`. It deliberately preserves its declared candidate-count mismatch. Do not invent or auto-fill a missing actor. Before live activation, verify the researcher-approved public accounts and resolve that mismatch in the private repository.

## Browser collection

Firefox capture remains manual and interactive. The shared backend must bind to loopback only:

```bash
set -a; source data/config/brazil26-localhost.env; set +a
bash scripts/run_firefox_study.sh data/config/brazil26.yaml data/browser/brazil26 8766
```

Use the shared Firefox extension for X, Instagram and TikTok. A synthetic public fixture is available in `configs/studies/brazil26.example.yaml`; it contains fictional handles only.

## Non-browser collection

Run one bounded localhost cycle with:

```bash
bash scripts/run_brazil26_localhost_collect.sh
```

One invocation uses one lock and one scheduler path for two canonical passes:

1. RSS/Atom through `laclaugpt-server-rss`.
2. Directly executable Phase 1 plugin rows through `brazil26_localhost_collect`. The current safe addition is YouTube when an approved manifest supplies explicit `video_urls`.

The checked-in `configs/studies/brazil26.sources.example.toml` provides a public-safe institutional baseline. Its YouTube entry names an official channel homepage for sampling provenance only, so the plugin pass skips it. Collection never enumerates or guesses videos from a channel URL. A private approved overlay may add explicit video URLs, which are then collected through the canonical YouTube plugin with `project_id=brazil26` and `collection_id=brazil26`.

Web-source rows remain documentary sampling inputs until a canonical web plugin exists. Browser targets remain manual and are never scheduled by this wrapper. Political identities, source-family labels and arena values are sampling provenance, not analytical labels.

Override `LACLAUGPT_SOURCE_MANIFEST` with an approved private manifest when required. The worker refuses a non-Brazil26 project id and always passes `--collection-id brazil26`.

## Sync, media and handoff

```bash
bash scripts/run_brazil26_localhost_sync.sh
bash scripts/run_brazil26_localhost_media.sh
laclaugpt-handoff --data-root ./data/browser/brazil26 --project-id brazil26 --collection-id brazil26 --limit 100
bash scripts/validate_installation.sh brazil26
python tools/verify_contracts.py
```

The same source URL may exist in AI26 and Brazil26. Handoff identity includes `collection_id`, so cross-study records receive different handoff keys and remain independently selectable downstream.

## Cron-safe operation

After manual validation:

```bash
bash scripts/install_cron_brazil26.sh
crontab -l
```

The collector/media wrappers use `flock`, and the cron installer owns a marker-delimited Brazil26 block. Logs are written under `data/logs/`. Firefox itself remains interactive and is not placed in cron.

## Public/private boundary

Safe to commit: runtime topology, synthetic browser fixtures, sampling/provenance rules and bounded public institutional examples.

Never commit: live operational target overlays, credentials, cookies, private endpoints, researcher machine paths, raw study data or downloaded private corpus material.
