#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/brazil26-localhost.env"}
STUDY_OVERRIDE=${LACLAUGPT_STUDY_CONFIG:-}
DATA_OVERRIDE=${LACLAUGPT_DATA_ROOT:-}
LOCK_FILE=${LACLAUGPT_SYNC_LOCK:-"$ROOT/data/tmp/brazil26-localhost-sync.lock"}

export PATH="$ROOT/.venv/bin:${HOME:-/root}/.local/bin:$PATH"
mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp"
[[ -f "$ENV_FILE" ]] || { echo "missing runtime env: $ENV_FILE" >&2; exit 2; }

cd "$ROOT"
set -a; source "$ENV_FILE"; set +a
STUDY_CONFIG=${STUDY_OVERRIDE:-${LACLAUGPT_STUDY_CONFIG:-${BRAZIL26_CONFIG:-"$ROOT/data/config/brazil26.yaml"}}}
DATA_ROOT=${DATA_OVERRIDE:-${LACLAUGPT_DATA_ROOT:-"$ROOT/data"}}
[[ -f "$STUDY_CONFIG" ]] || { echo "missing study config: $STUDY_CONFIG" >&2; exit 2; }
if [[ "${LACLAUGPT_PROJECT_ID:-brazil26}" != "brazil26" ]]; then
  echo "Brazil26 sync worker refuses a non-brazil26 project id" >&2
  exit 2
fi
export LACLAUGPT_PROJECT_ID=${LACLAUGPT_PROJECT_ID:-brazil26}
export LACLAUGPT_EXECUTION=cron
export LACLAUGPT_CALLER=cron

exec 9>"$LOCK_FILE"
flock -n 9 || { echo "Brazil26 sync already running; exiting cleanly" >&2; exit 0; }

cd "$ROOT"
exec laclaugpt-collect distributed-sync   --study-config "$STUDY_CONFIG"   --data-root "$DATA_ROOT"   --limit "${LACLAUGPT_SYNC_BATCH_LIMIT:-100}"
