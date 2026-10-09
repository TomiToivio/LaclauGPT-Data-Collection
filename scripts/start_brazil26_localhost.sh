#!/usr/bin/env bash
# One-command Brazil26 localhost start (issue #233).
#
# This is the documented single entry point for a researcher session: it
# resolves the same private study config, data root and runtime env that the
# cron wrappers use, then starts `laclaugpt-brazil26`. Pass --dry-run to print
# exactly what a real start would do (study, data root, Firefox command, cron
# policy, source policy) without starting a backend, launching a browser or
# touching the crontab; pass --distributed to require the CSC Allas / MongoDB
# preflight before a start (or in the dry-run plan).
#
# It deliberately duplicates NO runtime logic: the Python CLI owns preflight,
# the source policy, the cron block and the backend. Keeping the wrapper thin is
# what stops the plan from drifting from the real start.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/brazil26-localhost.env"}
STUDY_OVERRIDE=${LACLAUGPT_STUDY_CONFIG:-}
DATA_OVERRIDE=${LACLAUGPT_DATA_ROOT:-}
PRIVATE_ROOT=${LACLAUGPT_PRIVATE_REPO:-"$ROOT/../LaclauGPT-Private"}

export PATH="$ROOT/.venv/bin:${HOME:-/root}/.local/bin:$PATH"
mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp"

# A --dry-run only *prints* a plan, so it must work on a fresh checkout that has
# no runtime env yet. A real start requires the env file, exactly as the cron
# wrappers do.
DRY_RUN=0
for arg in "$@"; do
  [[ "$arg" == "--dry-run" ]] && DRY_RUN=1
done
if [[ $DRY_RUN -eq 0 ]]; then
  [[ -f "$ENV_FILE" ]] || { echo "missing runtime env: $ENV_FILE" >&2; exit 2; }
fi

cd "$ROOT"
if [[ -f "$ENV_FILE" ]]; then
  set -a; source "$ENV_FILE"; set +a
fi

# Same resolution order as install_cron_brazil26.sh: an explicit LACLAUGPT_*
# value wins, then the ignored env file, then the private-study default.
STUDY_CONFIG=${STUDY_OVERRIDE:-${LACLAUGPT_STUDY_CONFIG:-${BRAZIL26_CONFIG:-"$PRIVATE_ROOT/collection/brazil26/brazil-election-2026.yaml"}}}
DATA_ROOT=${DATA_OVERRIDE:-${LACLAUGPT_DATA_ROOT:-"$ROOT/data"}}

# A real start refuses a missing study config up front. A --dry-run instead lets
# the Python plan report it as a problem, so the plan is still printable on a
# checkout that is not fully configured yet.
if [[ $DRY_RUN -eq 0 ]]; then
  [[ -f "$STUDY_CONFIG" ]] || { echo "missing Brazil26 study config: $STUDY_CONFIG" >&2; exit 2; }
fi

command -v laclaugpt-brazil26 >/dev/null || {
  echo "laclaugpt-brazil26 missing; run scripts/install_common.sh first." >&2
  exit 2
}

exec laclaugpt-brazil26 \
  --study-config "$STUDY_CONFIG" \
  --data-root "$DATA_ROOT" \
  "$@"
