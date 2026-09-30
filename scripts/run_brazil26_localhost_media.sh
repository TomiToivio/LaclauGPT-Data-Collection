#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/brazil26-localhost.env"}
PRIVATE_ROOT=${LACLAUGPT_PRIVATE_REPO:-"$ROOT/../LaclauGPT-Private"}
export PATH="$ROOT/.venv/bin:${HOME:-/root}/.local/bin:$PATH"
mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp"
[[ -f "$ENV_FILE" ]] || { echo "missing runtime env: $ENV_FILE" >&2; exit 2; }
STUDY_OVERRIDE=${LACLAUGPT_STUDY_CONFIG:-}
DATA_OVERRIDE=${LACLAUGPT_DATA_ROOT:-}
set -a; source "$ENV_FILE"; set +a
# Resolve the private config after loading the ignored runtime environment.
STUDY_CONFIG=${STUDY_OVERRIDE:-${LACLAUGPT_STUDY_CONFIG:-${BRAZIL26_CONFIG:-"$PRIVATE_ROOT/collection/brazil26/brazil-election-2026.yaml"}}}
DATA_ROOT=${DATA_OVERRIDE:-${LACLAUGPT_DATA_ROOT:-"$ROOT/data"}}
LOCK_FILE=${LACLAUGPT_MEDIA_LOCK:-"$DATA_ROOT/tmp/brazil26-localhost-media.lock"}
[[ -f "$STUDY_CONFIG" ]] || { echo "missing study config: $STUDY_CONFIG" >&2; exit 2; }
if [[ "${LACLAUGPT_PROJECT_ID:-brazil26}" != "brazil26" ]]; then
  echo "Brazil26 media worker refuses a non-brazil26 project id" >&2
  exit 2
fi
export LACLAUGPT_PROJECT_ID=brazil26
export LACLAUGPT_EXECUTION=cron
export LACLAUGPT_CALLER=cron

# This wrapper is the zero-infrastructure localhost path, matching
# run_brazil26_localhost_collect.sh. A repo-root .env that points at a remote
# MongoDB/Redis/S3 must not silently switch the media pass into the distributed
# plane: that made every tick fail with "distributed collection requires
# LACLAUGPT_RUN_ID" and stopped media capture entirely. Objects stay in the
# local filesystem store and the existing SQLite media index tracks them.
# Explicit remote mirroring belongs to run_brazil26_localhost_sync.sh.
export LACLAUGPT_RECORD_BACKEND=csv
export LACLAUGPT_OBJECT_BACKEND=filesystem
export LACLAUGPT_CACHE_BACKEND=memory
export LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND=local
export LACLAUGPT_MESSAGING_BACKEND=none
export LACLAUGPT_TASK_QUEUE_BACKEND=direct
export LACLAUGPT_MONGODB_URI=
export LACLAUGPT_REDIS_URL=
export LACLAUGPT_S3_BUCKET=

mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "Brazil26 media worker already running; exiting cleanly" >&2; exit 0; }

cd "$ROOT"
exec laclaugpt-distributed-media \
  --study-config "$STUDY_CONFIG" \
  --data-root "$DATA_ROOT" \
  --workers "${LACLAUGPT_MEDIA_WORKERS:-2}" \
  --limit "${LACLAUGPT_MEDIA_BATCH_LIMIT:-50}" \
  --lock
