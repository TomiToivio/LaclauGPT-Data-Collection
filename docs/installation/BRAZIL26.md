# Brazil26 localhost operations

Install with:

```bash
bash scripts/install_common.sh
bash scripts/install_brazil26.sh
```

Private Brazil26 source lists, research settings, keyword/query sets and codebooks belong in `LaclauGPT-Private/collection/brazil26/`. Do not publish live election sampling frames in this repository.

Prepare a private `data/config/brazil26.sources.toml` (or point `LACLAUGPT_SOURCE_MANIFEST` to the private repository) before running the RSS worker.

Manual checks:

```bash
set -a; source data/config/brazil26-localhost.env; set +a
bash scripts/run_firefox_study.sh data/config/brazil26.yaml data/browser/brazil26 8766
bash scripts/run_brazil26_localhost_sync.sh
bash scripts/run_brazil26_localhost_collect.sh
bash scripts/run_brazil26_localhost_media.sh
bash scripts/validate_installation.sh brazil26
```

Use the existing distributed MongoDB and Redis settings. Use CSC `allas-conf` in S3 mode for Allas authentication instead of storing Allas keys in the project env.

After successful manual runs, install cron with `bash scripts/install_cron_brazil26.sh`.

Logs:
`data/logs/brazil26-sync.log`, `brazil26-collect.log`, `brazil26-media.log`.

The browser backend remains loopback-only and Firefox stays interactive.
