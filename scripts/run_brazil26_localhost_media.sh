#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/brazil26-localhost.env"}
PRIVATE_ROOT=${LACLAUGPT_PRIVATE_REPO:-"$ROOT/../LaclauGPT-Private"}
STUDY_CONFIG=${LACLAUGPT_STUDY_CONFIG:-"$PRIVATE_ROOT/collection/brazil26/brazil-election-2026.yaml"}
DATA_ROOT=${LACLAUGPT_DATA_ROOT:-"$ROOT/data"}
LOCK_FILE=${LACLAUGPT_MEDIA_LOCK:-"$ROOT/data/tmp/brazil26-localhost-media.lock"}

export PATH="$ROOT/.venv/bin:${HOME:-/root}/.local/bin:$PATH"
mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp"
[[ -f "$ENV_FILE" ]] || { echo "missing runtime env: $ENV_FILE" >&2; exit 2; }
[[ -f "$STUDY_CONFIG" ]] || { echo "missing study config: $STUDY_CONFIG" >&2; exit 2; }

set -a; source "$ENV_FILE"; set +a
export LACLAUGPT_PROJECT_ID=${LACLAUGPT_PROJECT_ID:-brazil26}
export LACLAUGPT_EXECUTION=cron
export LACLAUGPT_CALLER=cron

exec 9>"$LOCK_FILE"
flock -n 9 || { echo "Brazil26 media worker already running; exiting cleanly" >&2; exit 0; }

cd "$ROOT"
exec laclaugpt-distributed-media   --study-config "$STUDY_CONFIG"   --data-root "$DATA_ROOT"   --workers "${LACLAUGPT_MEDIA_WORKERS:-2}"   --limit "${LACLAUGPT_MEDIA_BATCH_LIMIT:-50}"   --lock
