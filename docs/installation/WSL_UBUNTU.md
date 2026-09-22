# WSL Ubuntu collection workstation

Issue #76 standardizes one deliberately simple deployment model:

**WSL Ubuntu localhost collectors/backends/downloaders/cron + distributed MongoDB/Redis + CSC Allas.**

## 1. Clone public and private repositories

Keep the repositories next to each other:

```text
~/src/LaclauGPT-Data-Collection
<private-config-checkout>
```

The public repository contains code, installers, examples and documentation. Real feeds, source lists, codebooks, endpoints and other research-sensitive settings belong under:

```text
<private-config-root>/ai26/
<private-config-root>/brazil26/
```

Do not copy those values into tracked public files.

## 2. Install common dependencies

```bash
cd ~/src/LaclauGPT-Data-Collection
bash scripts/install_common.sh
```

The installer creates `.venv`, installs `requirements.txt`, and creates ignored runtime directories under `data/`.

Firefox is interactive and intentionally not installed by the script. Windows Firefox can talk to a WSL service through localhost forwarding; whichever Firefox you use, the capture backend must remain bound to `127.0.0.1`.

## 3. Configure CSC Allas

Use CSC's `allas-conf` and select/configure S3 mode. The public repository must not contain Allas access keys. In S3 mode `allas-conf` manages the AWS credential/config files used by boto3.

Verify that `~/.aws/credentials` exists after configuration. Keep:

```bash
LACLAUGPT_OBJECT_BACKEND=s3
LACLAUGPT_S3_SIGNATURE_VERSION=s3
LACLAUGPT_S3_ADDRESSING_STYLE=auto
```

in the runtime environment. Do not add `LACLAUGPT_S3_ACCESS_KEY*` or secret-key values to the project env file when using `allas-conf`.

## 4. Prepare a project

```bash
bash scripts/install_ai26.sh
# or
bash scripts/install_brazil26.sh
```

Then edit the ignored project env under `data/config/` and point `LACLAUGPT_PRIVATE_CONFIG_DIR` at the corresponding directory in `LaclauGPT-Private`.

Use the existing distributed MongoDB and Redis URLs. Do not start local MongoDB/Redis copies merely for this workstation.

## 5. Browser collection

Start the local backend:

```bash
source .venv/bin/activate
set -a; source data/config/ai26-localhost.env; set +a
bash scripts/run_firefox_study.sh data/config/ai26.yaml data/browser/ai26 8765
```

For Brazil26 use its env, study file, data root and a different port such as 8766 if both are active.

Load `browser/firefox/manifest.json` as a temporary Firefox extension and configure it for the loopback backend.

## 6. Scheduled collection and media processing

Run every wrapper manually once before installing cron. Then:

```bash
bash scripts/install_cron_ai26.sh
bash scripts/install_cron_brazil26.sh
crontab -l
```

Logs are written below `data/logs/`; locks below `data/tmp/`; downloads/staging below `data/downloads/` and `data/staging/`.

## 7. Validate

```bash
bash scripts/validate_installation.sh ai26
bash scripts/validate_installation.sh brazil26
```

Validation checks the local runtime and live MongoDB/Redis/Allas-facing distributed configuration without printing credentials.

## 8. Restart and recovery

Cron wrappers are one-shot and protected by `flock`. A stale lock file is harmless unless a process still owns the lock.

To recover:

1. inspect `data/logs/<project>-*.log`;
2. run the failed wrapper manually with the same env;
3. run `scripts/validate_installation.sh <project>`;
4. check `crontab -l`;
5. re-run `allas-conf` if CSC credentials expired;
6. restart only the affected wrapper/backend.

## 9. Safe updates

```bash
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
bash scripts/validate_installation.sh ai26
```

Repeat for Brazil26 when that project is active. Runtime data and private configuration remain outside Git.
