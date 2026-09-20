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

The checked-in `configs/studies/brazil26.sources.example.toml` provides a public-safe institutional baseline. `scripts/install_brazil26.sh` copies it to `data/config/brazil26.sources.toml`. Override `LACLAUGPT_SOURCE_MANIFEST` with an approved private manifest when required. The worker refuses a non-Brazil26 project id and always passes `--collection-id brazil26`.

## Sync, media and handoff

```bash
bash scripts/run_brazil26_localhost_sync.sh
bash scripts/run_brazil26_localhost_media.sh
laclaugpt-handoff --data-root ./data/browser/brazil26 --project-id brazil26 --collection-id brazil26 --limit 100
bash scripts/validate_installation.sh brazil26
```

The same source URL may exist in AI26 and Brazil26. Handoff identity includes `collection_id`, so cross-study records receive different handoff keys and remain independently selectable downstream.

## Cron-safe operation

After manual validation:

```bash
bash scripts/install_cron_brazil26.sh
crontab -l
```

The collector/media wrappers use `flock`, and the cron installer owns a marker-delimited Brazil26 block. Logs are written under `data/logs/`.

## Public/private boundary

Safe to commit: runtime topology, synthetic browser fixtures, sampling/provenance rules and bounded public institutional examples.

Never commit: live operational target overlays, credentials, cookies, private endpoints, researcher machine paths, raw study data or downloaded private corpus material.
